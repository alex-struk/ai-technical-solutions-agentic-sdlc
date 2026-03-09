"""SRE Agent - Main entrypoint and monitoring loop.

Uses AutoGen with MCP tools to monitor Kubernetes deployments,
analyze issues with a local LLM, and create GitHub issues/PRs.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage
from autogen_core import CancellationToken

from llm_config import create_llm_client
from mcp_setup import get_github_tools, get_k8s_workbench
from prompts import SYSTEM_PROMPT, GITHUB_ISSUE_TEMPLATE
from tekton_client import create_remediation_run, generate_incident_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("sre-agent")

# Liveness probe file
HEALTHY_FILE = Path("/tmp/healthy")

# In-memory incident tracking: {incident_key: timestamp}
active_incidents: dict[str, float] = {}

# Shutdown flag
shutdown_event = asyncio.Event()


def handle_signal(sig, frame):
    logger.info("Received signal %s, shutting down...", sig)
    shutdown_event.set()


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


def touch_healthy():
    """Update liveness probe file."""
    HEALTHY_FILE.touch()


def is_on_cooldown(incident_key: str) -> bool:
    """Check if an incident is still within the cooldown period."""
    cooldown_minutes = int(os.environ.get("INCIDENT_COOLDOWN_MINUTES", "30"))
    last_time = active_incidents.get(incident_key)
    if last_time is None:
        return False
    elapsed = time.time() - last_time
    return elapsed < (cooldown_minutes * 60)


def record_incident(incident_key: str):
    """Record that an incident was acted on."""
    active_incidents[incident_key] = time.time()


async def gather_diagnostics(k8s_workbench) -> dict:
    """Call MCP tools directly to gather diagnostic info (no LLM needed)."""
    namespace = os.environ.get("TARGET_NAMESPACE", "fd34fb-prod")
    deployment = os.environ.get("TARGET_DEPLOYMENT", "test")
    results = []

    try:
        # 1. List pods in namespace
        pod_data = await k8s_workbench.call_tool(
            "pods_list_in_namespace", {"namespace": namespace}
        )
        pod_text = _extract_text(pod_data)
        results.append(f"=== Pods in {namespace} ===\n{pod_text}")

        # 2. Get events
        event_data = await k8s_workbench.call_tool(
            "events_list", {"namespace": namespace}
        )
        event_text = _extract_text(event_data)
        results.append(f"=== Events in {namespace} ===\n{event_text}")

        # 3. Get pod logs for the target deployment pods
        # Find pods matching the deployment
        pod_lines = pod_text.split("\n")
        for line in pod_lines:
            if deployment in line.lower():
                # Extract pod name (first column in table output)
                parts = line.split()
                if parts:
                    pod_name = parts[0]
                    try:
                        log_data = await k8s_workbench.call_tool(
                            "pods_log", {
                                "name": pod_name,
                                "namespace": namespace,
                                "tail": 50,
                            }
                        )
                        log_text = _extract_text(log_data)
                        results.append(f"=== Logs: {pod_name} ===\n{log_text}")
                    except Exception:
                        logger.debug("Could not get logs for pod %s", pod_name)

        raw_response = "\n\n".join(results)
        return {
            "raw_response": raw_response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "deployment": deployment,
            "namespace": namespace,
        }
    except Exception:
        logger.exception("Failed to gather diagnostics via k8s MCP")
        return {
            "error": "Failed to query Kubernetes API",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "deployment": deployment,
            "namespace": namespace,
        }


def _extract_text(tool_result) -> str:
    """Extract text from MCP tool result (handles various return formats)."""
    if isinstance(tool_result, str):
        return tool_result
    if isinstance(tool_result, dict):
        # MCP tool results often have 'content' with list of text blocks
        content = tool_result.get("content", [])
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    texts.append(item.get("text", str(item)))
                else:
                    texts.append(str(item))
            return "\n".join(texts)
        return str(content)
    if isinstance(tool_result, list):
        return "\n".join(str(item) for item in tool_result)
    if hasattr(tool_result, "content"):
        # MCP CallToolResult object
        content = tool_result.content
        if isinstance(content, list):
            return "\n".join(
                item.text if hasattr(item, "text") else str(item)
                for item in content
            )
        return str(content)
    return str(tool_result)


async def analyze_with_llm(llm_client, diagnostics: dict) -> dict:
    """Send diagnostics to the LLM for root cause analysis."""
    from autogen_core.models import UserMessage, SystemMessage

    raw = diagnostics.get("raw_response", json.dumps(diagnostics, indent=2))
    deployment = diagnostics.get("deployment", "test")

    # Filter to only include lines relevant to the target deployment
    # This prevents truncation from cutting off the important data
    relevant_lines = []
    for line in raw.split("\n"):
        lower = line.lower()
        if deployment.lower() in lower or line.startswith("==="):
            relevant_lines.append(line)
    filtered = "\n".join(relevant_lines) if relevant_lines else raw

    # Truncate to fit within llama.cpp context window (4096 tokens)
    diagnostic_text = filtered[:2000]
    if len(filtered) > 2000:
        diagnostic_text += "\n[truncated]"

    try:
        result = await llm_client.create(
            messages=[
                SystemMessage(content=SYSTEM_PROMPT),
                UserMessage(content=diagnostic_text, source="user"),
            ],
        )

        response_text = result.content
        if isinstance(response_text, list):
            response_text = response_text[0].text if response_text else ""

        # Try to parse as JSON
        try:
            # Strip markdown code blocks if present
            clean = response_text.strip()
            if clean.startswith("```"):
                # Remove ```json and trailing ```
                lines = clean.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                clean = "\n".join(lines)
            # Find JSON in response (model might add text around it)
            start = clean.index("{")
            # Find matching closing brace by trying progressively
            analysis = None
            for i in range(start + 1, len(clean)):
                if clean[i] == "}":
                    try:
                        analysis = json.loads(clean[start:i + 1])
                        break
                    except json.JSONDecodeError:
                        continue
            if analysis is None:
                raise ValueError("No valid JSON found")
            # Ensure no None values in required fields
            analysis.setdefault("root_cause", "Unknown")
            analysis.setdefault("severity", "warning")
            analysis.setdefault("suggested_fix", "Manual investigation required")
            analysis.setdefault("fix_type", "none")
            # Replace explicit None values
            for key in ("root_cause", "severity", "suggested_fix", "fix_type"):
                if analysis[key] is None:
                    analysis[key] = {"root_cause": "Unknown", "severity": "warning",
                                     "suggested_fix": "Manual investigation required",
                                     "fix_type": "none"}[key]
        except (ValueError, json.JSONDecodeError):
            logger.warning("LLM response was not valid JSON, using raw text")
            analysis = {
                "root_cause": response_text,
                "severity": "warning",
                "suggested_fix": "Manual investigation required",
                "fix_type": "none",
                "fix_details": {"action": "none", "target": "", "params": {}},
            }

        return analysis
    except Exception:
        logger.exception("LLM analysis failed")
        return {
            "root_cause": "LLM analysis unavailable",
            "severity": "warning",
            "suggested_fix": "Check LLM endpoint connectivity",
            "fix_type": "none",
            "fix_details": {"action": "none", "target": "", "params": {}},
        }


def detect_issue_type(diagnostics: dict) -> str | None:
    """Detect issue type from pod status, scoped to the target deployment only.

    Only examines the pod list section (not events) to avoid false positives
    from stale events. Checks if any target deployment pod has a non-Running status.
    """
    raw = diagnostics.get("raw_response", "").lower()
    deployment = diagnostics.get("deployment", "test").lower()

    # Extract pod list section only (before events section)
    pod_section = raw.split("=== events")[0] if "=== events" in raw else raw

    # Find pod lines for the target deployment
    target_pod_lines = [
        line for line in pod_section.split("\n")
        if deployment in line and "pod" in line
    ]

    if not target_pod_lines:
        return None  # No target pods found at all

    for line in target_pod_lines:
        if "crashloopbackoff" in line:
            return "crashloop"
        if "oomkilled" in line:
            return "oomkilled"
        if "imagepullbackoff" in line or "errimagepull" in line:
            return "image_pull"
        if "error" in line and "running" not in line:
            return "pod_error"
        # Check for non-running pods (but not completed jobs)
        if "running" not in line and "completed" not in line and "succeeded" not in line:
            if any(s in line for s in ["pending", "terminated", "waiting", "init"]):
                return "pod_unhealthy"

    return None


def _build_issue_body(analysis: dict, diagnostics: dict) -> tuple[str, str]:
    """Build GitHub issue title and body."""
    repo = os.environ.get("GITHUB_REPO", "strukalex/rhdh-test")
    model = os.environ.get("LLM_MODEL", "phi-4-mini")

    title = f"[SRE Agent] {analysis.get('severity', 'warning').upper()}: {analysis.get('root_cause', 'Unknown issue')[:80]}"

    body = GITHUB_ISSUE_TEMPLATE.format(
        deployment=diagnostics.get("deployment", "unknown"),
        namespace=diagnostics.get("namespace", "unknown"),
        timestamp=diagnostics.get("timestamp", "unknown"),
        severity=analysis.get("severity", "unknown"),
        root_cause=analysis.get("root_cause", "Unknown"),
        suggested_fix=analysis.get("suggested_fix", "None"),
        pod_status=diagnostics.get("raw_response", "N/A")[:2000],
        events="See pod status above",
        logs="See pod status above",
        model=model,
    )
    return title, body


async def create_github_issue_via_agent(
    github_agent: AssistantAgent,
    analysis: dict,
    diagnostics: dict,
) -> str | None:
    """Create a GitHub issue using the AssistantAgent with MCP tools."""
    repo = os.environ.get("GITHUB_REPO", "strukalex/rhdh-test")
    title, body = _build_issue_body(analysis, diagnostics)

    prompt = f"""Create a GitHub issue in repository {repo} with:
Title: {title}
Labels: sre-agent, incident
Body:
{body}"""

    try:
        response = await github_agent.on_messages(
            [TextMessage(content=prompt, source="user")],
            cancellation_token=CancellationToken(),
        )
        logger.info("GitHub issue creation response: %s", response.chat_message.content[:200])
        return response.chat_message.content
    except Exception:
        logger.exception("Failed to create GitHub issue via agent")
        return None


async def create_github_issue_via_workbench(
    workbench,
    analysis: dict,
    diagnostics: dict,
) -> str | None:
    """Create a GitHub issue using McpWorkbench direct tool call."""
    repo = os.environ.get("GITHUB_REPO", "strukalex/rhdh-test")
    owner, repo_name = repo.split("/", 1)
    title, body = _build_issue_body(analysis, diagnostics)

    try:
        result = await workbench.call_tool(
            "create_issue",
            {
                "owner": owner,
                "repo": repo_name,
                "title": title,
                "body": body,
                "labels": ["sre-agent", "incident"],
            },
        )
        logger.info("GitHub issue created via workbench: %s", str(result)[:200])
        return str(result)
    except Exception:
        logger.exception("Failed to create GitHub issue via workbench")
        return None


async def handle_incident(
    analysis: dict,
    diagnostics: dict,
    github_agent: AssistantAgent | None,
    github_workbench,
    issue_type: str,
):
    """Handle a detected incident: create issue, trigger remediation."""
    deployment = diagnostics.get("deployment", "unknown")
    incident_id = generate_incident_id(deployment, issue_type)
    incident_key = f"{issue_type}:{deployment}"

    if is_on_cooldown(incident_key):
        logger.info("Incident %s is on cooldown, skipping", incident_key)
        return

    record_incident(incident_key)

    severity = analysis.get("severity", "warning")
    logger.info(
        "INCIDENT DETECTED [%s] %s: %s",
        severity.upper(),
        incident_key,
        analysis.get("root_cause", "Unknown"),
    )

    # Create GitHub issue
    if github_agent:
        await create_github_issue_via_agent(github_agent, analysis, diagnostics)
    elif github_workbench:
        await create_github_issue_via_workbench(github_workbench, analysis, diagnostics)

    # Create Tekton PipelineRun for remediation (only for actionable fixes)
    fix_type = analysis.get("fix_type", "none")
    if fix_type != "none":
        run_name = create_remediation_run(
            incident_id=incident_id,
            action_type=fix_type,
            target_resource=analysis.get("fix_details", {}).get("target", deployment),
            description=f"{analysis.get('root_cause', '')}\n\nSuggested fix: {analysis.get('suggested_fix', '')}",
        )
        if run_name:
            logger.info("Remediation PipelineRun created: %s (awaiting approval)", run_name)
        else:
            logger.warning("Failed to create remediation PipelineRun")


async def monitoring_loop(
    k8s_workbench,
    github_agent: AssistantAgent | None,
    github_workbench,
    llm_client,
):
    """Main monitoring loop."""
    check_interval = int(os.environ.get("CHECK_INTERVAL", "60"))
    logger.info(
        "Starting monitoring loop (interval=%ds, deployment=%s, namespace=%s)",
        check_interval,
        os.environ.get("TARGET_DEPLOYMENT", "test"),
        os.environ.get("TARGET_NAMESPACE", "fd34fb-prod"),
    )

    while not shutdown_event.is_set():
        try:
            touch_healthy()

            # Step 1: Gather diagnostics (direct MCP calls, no LLM)
            logger.info("--- Check cycle start ---")
            diagnostics = await gather_diagnostics(k8s_workbench)

            if "error" in diagnostics:
                logger.error("Diagnostics gathering failed: %s", diagnostics["error"])
                await asyncio.sleep(check_interval)
                continue

            # Step 2: Detect issues
            issue_type = detect_issue_type(diagnostics)

            if issue_type is None:
                logger.info("All healthy - no issues detected")
                await asyncio.sleep(check_interval)
                continue

            logger.info("Potential issue detected: %s", issue_type)

            # Step 3: Analyze with LLM
            analysis = await analyze_with_llm(llm_client, diagnostics)
            logger.info(
                "LLM analysis: severity=%s, fix_type=%s, root_cause=%s",
                analysis.get("severity"),
                analysis.get("fix_type"),
                (analysis.get("root_cause") or "")[:100],
            )

            # Step 4: Handle incident
            if analysis.get("severity") in ("critical", "warning"):
                await handle_incident(analysis, diagnostics, github_agent, github_workbench, issue_type)

        except Exception:
            logger.exception("Error in monitoring loop")

        # Wait for next cycle or shutdown
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=check_interval)
        except asyncio.TimeoutError:
            pass

    logger.info("Monitoring loop stopped")


async def main():
    logger.info("SRE Agent starting up...")

    # Initialize LLM client
    logger.info("Initializing LLM client...")
    llm_client = create_llm_client()

    # Initialize MCP connections
    logger.info("Connecting to MCP servers...")
    k8s_workbench = await get_k8s_workbench()
    github_tools = await get_github_tools()

    if not k8s_workbench:
        logger.error("Kubernetes MCP workbench unavailable - cannot monitor. Exiting.")
        sys.exit(1)

    # GitHub tools setup
    github_agent = None
    github_workbench = None
    if isinstance(github_tools, list) and github_tools:
        github_agent = AssistantAgent(
            name="github_assistant",
            model_client=llm_client,
            tools=github_tools,
            system_message=(
                "You are a GitHub assistant. Use the available tools to create issues "
                "and pull requests. Always include the sre-agent label on issues."
            ),
        )
    elif hasattr(github_tools, "call_tool"):
        github_workbench = github_tools
        logger.info("Using GitHub McpWorkbench for direct tool calls")
    else:
        logger.warning("GitHub MCP tools unavailable - issue/PR creation disabled")

    # Start monitoring
    touch_healthy()
    await monitoring_loop(k8s_workbench, github_agent, github_workbench, llm_client)

    logger.info("SRE Agent shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
