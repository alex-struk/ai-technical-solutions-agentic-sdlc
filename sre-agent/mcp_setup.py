"""MCP server connection setup for the SRE agent."""

import asyncio
import os
import logging

from autogen_ext.tools.mcp import SseServerParams, StdioServerParams, mcp_server_tools

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_DELAY = 10  # seconds


async def get_k8s_workbench():
    """Connect to the Kubernetes MCP server via SSE and return a McpWorkbench.

    We use McpWorkbench for direct tool calls (no LLM involved in tool selection).
    This avoids sending all 14 tool schemas to the small model.
    """
    from autogen_ext.tools.mcp import McpWorkbench

    url = os.environ.get("K8S_MCP_URL", "http://k8s-mcp-server:8080/sse")
    logger.info("Connecting to Kubernetes MCP server at %s", url)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            workbench = McpWorkbench(SseServerParams(url=url))
            await workbench.start()
            tools = await workbench.list_tools()
            logger.info("Kubernetes McpWorkbench: %d tools available", len(tools))
            for tool in tools:
                name = tool.get("name", tool) if isinstance(tool, dict) else getattr(tool, "name", str(tool))
                logger.info("  - %s", name)
            return workbench
        except Exception:
            logger.warning(
                "K8s MCP connection attempt %d/%d failed, retrying in %ds...",
                attempt, MAX_RETRIES, RETRY_DELAY,
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            else:
                logger.exception("Failed to connect to Kubernetes MCP server after %d attempts", MAX_RETRIES)
    return None


async def get_github_tools():
    """Connect to the GitHub MCP server via STDIO (binary in container).

    Note: The GitHub MCP server exposes tools with complex JSON schemas that
    may trigger autogen's schema-to-pydantic conversion bugs. If tool loading
    fails, we fall back to using McpWorkbench for direct tool invocation.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        logger.warning("GITHUB_TOKEN not set, GitHub MCP tools unavailable")
        return []

    logger.info("Starting GitHub MCP server via STDIO")
    try:
        tools = await mcp_server_tools(StdioServerParams(
            command="/usr/local/bin/github-mcp-server",
            args=["stdio"],
            env={
                "GITHUB_PERSONAL_ACCESS_TOKEN": token,
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            },
        ))
        logger.info("GitHub MCP: %d tools available", len(tools))
        for tool in tools:
            logger.info("  - %s", tool.name)
        return tools
    except TypeError as e:
        # Known autogen bug: complex JSON schemas (e.g. list types) cause
        # "unhashable type: 'list'" in schema_to_pydantic_model.
        # Fall back to McpWorkbench for direct tool calls.
        logger.warning("GitHub MCP schema conversion failed (%s), using McpWorkbench fallback", e)
        return await _get_github_workbench(token)
    except Exception:
        logger.exception("Failed to start GitHub MCP server")
        return []


async def _get_github_workbench(token: str):
    """Use McpWorkbench as fallback for GitHub MCP when tool adapter fails."""
    try:
        from autogen_ext.tools.mcp import McpWorkbench

        workbench = McpWorkbench(StdioServerParams(
            command="/usr/local/bin/github-mcp-server",
            args=["stdio"],
            env={
                "GITHUB_PERSONAL_ACCESS_TOKEN": token,
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            },
        ))
        await workbench.start()
        tools = await workbench.list_tools()
        logger.info("GitHub McpWorkbench: %d tools available", len(tools))
        for tool in tools:
            name = tool.get("name", tool) if isinstance(tool, dict) else getattr(tool, "name", str(tool))
            logger.info("  - %s", name)
        # Return the workbench itself - agent.py will need to handle this differently
        return workbench
    except Exception:
        logger.exception("GitHub McpWorkbench fallback also failed")
        return []
