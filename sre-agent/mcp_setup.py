"""MCP server connection setup for the SRE agent."""

import os
import logging

from autogen_ext.tools.mcp import SseServerParams, StdioServerParams, mcp_server_tools

logger = logging.getLogger(__name__)


async def get_k8s_tools():
    """Connect to the Kubernetes MCP server via SSE."""
    url = os.environ.get("K8S_MCP_URL", "http://k8s-mcp-server:8080/sse")
    logger.info("Connecting to Kubernetes MCP server at %s", url)
    try:
        tools = await mcp_server_tools(SseServerParams(url=url))
        logger.info("Kubernetes MCP: %d tools available", len(tools))
        for tool in tools:
            logger.info("  - %s", tool.name)
        return tools
    except Exception:
        logger.exception("Failed to connect to Kubernetes MCP server")
        return []


async def get_github_tools():
    """Connect to the GitHub MCP server via STDIO (binary in container)."""
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
    except Exception:
        logger.exception("Failed to start GitHub MCP server")
        return []
