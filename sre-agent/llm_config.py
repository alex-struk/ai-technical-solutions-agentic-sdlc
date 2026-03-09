"""LLM client configuration for the SRE agent."""

import os

from autogen_ext.models.openai import OpenAIChatCompletionClient


def create_llm_client() -> OpenAIChatCompletionClient:
    """Create an OpenAI-compatible client pointing to the local qwen2.5-3b."""
    endpoint = os.environ["LLM_ENDPOINT"]
    # Strip /v1/chat/completions suffix if present to get base URL
    base_url = endpoint.split("/v1/chat/completions")[0]
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    return OpenAIChatCompletionClient(
        model=os.environ.get("LLM_MODEL", "qwen2.5-3b-instruct-q4_k_m"),
        base_url=base_url,
        api_key=os.environ.get("LLM_API_KEY", "no-key"),
        model_info={
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "family": "unknown",
        },
        temperature=0.1,
        max_tokens=500,
    )
