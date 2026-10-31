"""LLM clients.

``MockLLM`` replays canned JSON responses from a scenario's ``mock/`` folder so runs are
deterministic, free and work offline (tests, CI, demos). Response files are chosen per call:
``<stage>.<n>.json`` for the n-th call to that stage if present, else ``<stage>.json``. That
lets a scenario script a bad first answer and a corrected second one.

``ClaudeLLM`` calls the Anthropic API (``LLM_MODE=live``). Every agent asks for JSON only, and
the response is parsed and validated by the agent, never executed.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Protocol

from orchestrator.models import TransientError

SYSTEM_PROMPT = (
    "You are one agent in a governed software-delivery pipeline for a Python FastAPI URL "
    "shortener service. Follow the requested JSON schema exactly. Reply with a single JSON "
    "object and nothing else. Never include secrets or credentials. Keep changes minimal, "
    "consistent with the existing code style, and fully tested."
)


class LLM(Protocol):
    name: str

    def complete(self, stage: str, prompt: str, call_index: int) -> dict[str, Any]: ...


class MockLLM:
    name = "mock"

    def __init__(self, mock_dir: Path) -> None:
        self.mock_dir = mock_dir

    def complete(self, stage: str, prompt: str, call_index: int) -> dict[str, Any]:
        for candidate in (f"{stage}.{call_index}.json", f"{stage}.json"):
            path = self.mock_dir / candidate
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        raise FileNotFoundError(f"no mock response for stage {stage!r} in {self.mock_dir}")


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating a ```json fence around it."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find("{") : text.rfind("}") + 1]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise TransientError(f"model did not return valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise TransientError("model returned JSON that is not an object")
    return value


class ClaudeLLM:  # pragma: no cover - needs network and an API key
    name = "claude"

    def __init__(self, model: str | None = None, max_tokens: int = 8000) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "live mode needs the anthropic package: pip install anthropic"
            ) from exc
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("live mode needs ANTHROPIC_API_KEY set (see .env.example)")
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.max_tokens = max_tokens

    def complete(self, stage: str, prompt: str, call_index: int) -> dict[str, Any]:
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except (self._anthropic.RateLimitError, self._anthropic.APIConnectionError) as exc:
            raise TransientError(str(exc)) from exc
        text = "".join(getattr(block, "text", "") for block in msg.content)
        return extract_json(text)


def build_llm(mode: str, mock_dir: Path) -> LLM:
    if mode == "mock":
        return MockLLM(mock_dir)
    if mode == "live":  # pragma: no cover
        return ClaudeLLM()
    raise ValueError(f"unknown LLM mode {mode!r} (use 'mock' or 'live')")
