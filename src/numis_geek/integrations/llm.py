"""Spec 38 — Anthropic Claude wrapper for the extraction service.

The Anthropic SDK is an optional dependency (`pyproject.toml [llm]`). The
client is lazy-imported and tests can override the protocol via the
`set_llm_client` injection hook below.

Cost is tracked per-call so the admin observability page can report
monthly spend.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.orm import Session

from numis_geek.models.integration_credential import (
    IntegrationCredential, IntegrationProvider,
)


# Sonnet 4.5 — solid quality at ~$3 in / $15 out per MTok (USD).
DEFAULT_MODEL = "claude-sonnet-4-5"

# Pricing in USD per 1M tokens. Update when Anthropic changes the price list.
PRICING: dict[str, tuple[Decimal, Decimal]] = {
    "claude-sonnet-4-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-sonnet-4-6": (Decimal("3.00"), Decimal("15.00")),
    "claude-opus-4-7":   (Decimal("15.00"), Decimal("75.00")),
    "claude-haiku-4-5":  (Decimal("1.00"),  Decimal("5.00")),
}


@dataclass
class LLMCall:
    """Result of one Claude call."""
    text: str
    input_tokens: int
    output_tokens: int
    model: str

    def cost_usd(self) -> Decimal:
        in_price, out_price = PRICING.get(self.model, (Decimal("0"), Decimal("0")))
        return (
            (Decimal(self.input_tokens) / Decimal(1_000_000)) * in_price
            + (Decimal(self.output_tokens) / Decimal(1_000_000)) * out_price
        ).quantize(Decimal("0.0001"))


class LLMClient(Protocol):
    """Minimal protocol so tests can inject a fake without the SDK."""

    def call(
        self,
        *,
        system: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime: str | None = None,
        image_parts: list[tuple[bytes, str | None]] | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
    ) -> LLMCall: ...


# ── default Anthropic-backed client ──────────────────────────────────────────

class AnthropicClient:
    """Real Claude API wrapper. Lazy-imports the SDK so the rest of the
    codebase works without the optional dependency."""

    def __init__(self, api_key: str):
        try:
            from anthropic import Anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK not installed — install via `pip install -e .[llm]` "
                "or inject a mock via `set_llm_client(...)`.",
            ) from exc
        self._sdk = Anthropic(api_key=api_key)

    def call(
        self,
        *,
        system: str,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime: str | None = None,
        image_parts: list[tuple[bytes, str | None]] | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
    ) -> LLMCall:
        # `image_parts` is the tile list (Spec 48 — tall screenshots get
        # split into multiple sub-8000px tiles). Falls back to the legacy
        # single-image kwargs for callers that haven't migrated yet.
        parts: list[tuple[bytes, str | None]] = (
            image_parts
            if image_parts is not None
            else ([(image_bytes, image_mime)] if image_bytes else [])
        )
        content: list[dict[str, Any]] = []
        for blob, mime in parts:
            if not blob:
                continue
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime or "image/png",
                    "data": base64.b64encode(blob).decode("ascii"),
                },
            })
        content.append({"type": "text", "text": user_text})

        message = self._sdk.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        # `message.content` is a list of TextBlock-like objects.
        text_parts = [b.text for b in message.content if getattr(b, "type", None) == "text"]
        text = "\n".join(text_parts)
        return LLMCall(
            text=text,
            input_tokens=getattr(message.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(message.usage, "output_tokens", 0) or 0,
            model=getattr(message, "model", model) or model,
        )


# ── injection hook ───────────────────────────────────────────────────────────

_injected_client: LLMClient | None = None


def set_llm_client(client: LLMClient | None) -> None:
    """Override the LLM client (used by tests). Pass `None` to reset."""
    global _injected_client
    _injected_client = client


def get_llm_client(db: Session) -> LLMClient:
    """Return the currently-configured LLM client.

    Resolution order:
    1. Injected client (tests).
    2. Real Anthropic client built from the stored credential.
    """
    if _injected_client is not None:
        return _injected_client

    cred = (
        db.query(IntegrationCredential)
        .filter(
            IntegrationCredential.provider == IntegrationProvider.ANTHROPIC,
            IntegrationCredential.is_active == True,  # noqa: E712
        )
        .order_by(IntegrationCredential.updated_at.desc())
        .first()
    )
    if cred is None:
        raise RuntimeError(
            "No active ANTHROPIC IntegrationCredential. Configure one via "
            "/sysadmin/integrations or inject a mock via `set_llm_client(...)`.",
        )
    return AnthropicClient(cred.secret_value)


def parse_json_block(text: str) -> dict:
    """Extract the first JSON object from the LLM reply.

    Claude tends to wrap JSON in ```json fences. This helper handles fenced
    blocks, raw JSON, or "here's the JSON:" prefixed responses.
    """
    text = text.strip()

    # Strip ```json ... ``` fence if present.
    if text.startswith("```"):
        fenced = text.strip("`").strip()
        # Drop the leading "json\n" hint when Claude includes it.
        if fenced.lower().startswith("json"):
            fenced = fenced[4:].lstrip("\n")
        # Trim trailing "```" if it survived.
        fenced = fenced.rstrip("`").strip()
        text = fenced

    # If there's prose before the JSON, find the first `{` and the matching `}`.
    if not text.startswith("{"):
        start = text.find("{")
        if start == -1:
            raise ValueError("LLM reply contained no JSON object")
        # Find matching brace by depth — naive but enough for our prompts.
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            raise ValueError("LLM reply has unterminated JSON object")
        text = text[start : end + 1]

    return json.loads(text)
