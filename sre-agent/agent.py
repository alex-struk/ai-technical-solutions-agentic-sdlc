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
from mcp_setup import get_github_tools, get_k8s_tools
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


async def gather_diagnostics(k8s_agent: AssistantAgent) -> dict:
    """Use the k8s MCP tools via the agent to gather diagnostic info."""
    namespace = os.environ.get("TARGET_NAMESPACE", "fd34fb-prod")
    deployment = os.environ.get("TARGET_DEPLOYMENT", "test")

    prompt = f"""Check the health of deployment '{deployment}' in namespace '{namespace}'.
Run these checks:
1. List pods with label selector app={deployment} in namespace {namespace}
2. Get events in namespace {namespace} related to the deployment
3. If any pod is not in Running state or has restarts > 0, get its logs

Return all findings as a structured summary."""

    try:
        response = await k8s_agent.on_messages(
            [TextMessage(content=prompt, source="user")],
            cancellation_token=CancellationToken(),
        )
        return {
            "raw_response": response.chat_message.content,
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


async def analyze_with_llm(llm_client, diagnostics: dict) -> dict:
    """Send diagnostics to the LLM for root cause analysis."""
    from autogen_core.models import UserMessage, SystemMessage

    diagnostic_text = diagnostics.get("raw_response", json.dumps(diagnostics, indent=2))

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
            # Find JSON in response (model might add text around it)
            start = response_text.index("{")
            end = response_text.rindex("}") + 1
            analysis = json.loads(response_text[start:end])
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
    """Simple heuristic to detect issue type from diagnostics."""
    raw = diagnostics.get("raw_response", "").lower()
    if "crashloopbackoff" in raw or "crash" in raw:
        return "crashloop"
    if "oomkilled" in raw or "oom" in raw:
        return "oomkilled"
    if "error" in raw and ("500" in raw or "connection refused" in raw):
        return "app_error"
    if "imagepullbackoff" in raw or "errimagepull" in raw:
        return "image_pull"
    if "not found" in raw or "missing" in raw:
        return "missing_resource"
    return None


async def create_github_issue(
    github_agent: AssistantAgent,
    analysis: dict,
    diagnostics: dict,
) -> str | None:
    """Create a GitHub issue with the incident analysis."""
    repo = os.environ.get("GITHUB_REPO", "strukalex/rhdh-test")
    model = os.environ.get("LLM_MODEL", "qwen2.5-3b")

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
        logger.exception("Failed to create GitHub issue")
        return None


async def handle_incident(
    analysis: dict,
    diagnostics: dict,
    github_agent: AssistantAgent | None,
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
        await create_github_issue(github_agent, analysis, diagnostics)

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
    k8s_agent: AssistantAgent,
    github_agent: AssistantAgent | None,
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

            # Step 1: Gather diagnostics
            logger.info("--- Check cycle start ---")
            diagnostics = await gather_diagnostics(k8s_agent)

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
                analysis.get("root_cause", "")[:100],
            )

            # Step 4: Handle incident
            if analysis.get("severity") in ("critical", "warning"):
                await handle_incident(analysis, diagnostics, github_agent, issue_type)

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

    # Initialize MCP tools
    logger.info("Connecting to MCP servers...")
    k8s_tools = await get_k8s_tools()
    github_tools = await get_github_tools()

    if not k8s_tools:
        logger.error("No Kubernetes MCP tools available - cannot monitor. Exiting.")
        sys.exit(1)

    # Create agents
    k8s_agent = AssistantAgent(
        name="k8s_monitor",
        model_client=llm_client,
        tools=k8s_tools,
        system_message=(
            "You are a Kubernetes monitoring assistant. "
            "Use the available tools to check pod status, fetch logs, and get events. "
            "Return structured diagnostic information."
        ),
    )

    github_agent = None
    if github_tools:
        github_agent = AssistantAgent(
            name="github_assistant",
            model_client=llm_client,
            tools=github_tools,
            system_message=(
                "You are a GitHub assistant. Use the available tools to create issues "
                "and pull requests. Always include the sre-agent label on issues."
            ),
        )
    else:
        logger.warning("GitHub MCP tools unavailable - issue/PR creation disabled")

    # Start monitoring
    touch_healthy()
    await monitoring_loop(k8s_agent, github_agent, llm_client)

    logger.info("SRE Agent shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
