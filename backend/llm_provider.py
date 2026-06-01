"""LLM provider abstraction.

Lets the same calling code work in two modes:

  LLM_PROVIDER=emergent   (default — uses EMERGENT_LLM_KEY via emergentintegrations)
  LLM_PROVIDER=direct     (uses OPENAI_API_KEY + ANTHROPIC_API_KEY via official SDKs)

Why: the Emergent Universal Key only works on Emergent infra. For
self-hosted deployments (e.g. Hostinger VPS), switch to LLM_PROVIDER=direct
and supply your own provider keys.

Public API:
    await chat(provider="openai|anthropic", model="<name>",
               system="<system prompt>", user="<user message>") -> str
"""
from __future__ import annotations

import logging
import os
import uuid

logger = logging.getLogger("algoforge.llm_provider")


def get_mode() -> str:
    return os.environ.get("LLM_PROVIDER", "emergent").strip().lower()


def status() -> dict:
    mode = get_mode()
    if mode == "direct":
        return {
            "mode": "direct",
            "openai": "configured" if os.environ.get("OPENAI_API_KEY") else "missing OPENAI_API_KEY",
            "anthropic": "configured" if os.environ.get("ANTHROPIC_API_KEY") else "missing ANTHROPIC_API_KEY",
        }
    return {
        "mode": "emergent",
        "emergent_llm_key": "configured" if os.environ.get("EMERGENT_LLM_KEY") else "missing EMERGENT_LLM_KEY",
    }


async def _chat_emergent(provider: str, model: str, system: str, user: str) -> str:
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: WPS433
    key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        raise RuntimeError("EMERGENT_LLM_KEY missing — set it or switch LLM_PROVIDER=direct")
    instance = LlmChat(api_key=key, session_id=str(uuid.uuid4()), system_message=system).with_model(provider, model)
    return await instance.send_message(UserMessage(text=user))


async def _chat_openai(model: str, system: str, user: str) -> str:
    from openai import AsyncOpenAI  # noqa: WPS433
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing for LLM_PROVIDER=direct")
    client = AsyncOpenAI(api_key=key)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


async def _chat_anthropic(model: str, system: str, user: str) -> str:
    from anthropic import AsyncAnthropic  # noqa: WPS433
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY missing for LLM_PROVIDER=direct")
    client = AsyncAnthropic(api_key=key)
    resp = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # anthropic returns content as a list of blocks.
    out = []
    for block in resp.content:
        text = getattr(block, "text", None)
        if text:
            out.append(text)
    return "".join(out)


async def chat(provider: str, model: str, system: str, user: str) -> str:
    """Unified call. provider ∈ {'openai','anthropic'}. Picks mode based on env."""
    mode = get_mode()
    if mode == "direct":
        if provider == "openai":
            return await _chat_openai(model, system, user)
        if provider == "anthropic":
            return await _chat_anthropic(model, system, user)
        raise ValueError(f"Unknown provider: {provider}")
    return await _chat_emergent(provider, model, system, user)
