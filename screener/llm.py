"""Thin wrapper around the Claude API for structured-output calls.

Every call returns a validated pydantic object. `DryRunLLM` replays canned responses from
samples/fixtures/ so the whole pipeline can be exercised without an API key.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, TypeVar

import anthropic
from pydantic import BaseModel

from .config import LLMConfig

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_CONTINUATIONS = 5


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, cfg: LLMConfig):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError(
                "ANTHROPIC_API_KEY is not set. Export it (see .env.example), "
                "or run with --dry-run to use canned sample responses."
            )
        self.cfg = cfg
        self.client = anthropic.Anthropic()

    def parse(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        tools: Optional[list[dict]] = None,
        fixture_key: Optional[str] = None,  # unused here; part of the shared interface
    ) -> T:
        effort = getattr(self.cfg.effort, task)
        messages: list[dict] = [{"role": "user", "content": user}]
        kwargs: dict = dict(
            model=self.cfg.model,
            max_tokens=self.cfg.max_tokens,
            # System prompt (resume + preferences) is identical across a batch -> cache it.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_format=schema,
            output_config={"effort": effort},
        )
        if tools:
            kwargs["tools"] = tools
        if self.cfg.refusal_fallback:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        try:
            for _ in range(MAX_CONTINUATIONS):
                resp = self.client.beta.messages.parse(messages=messages, **kwargs)
                if resp.stop_reason != "pause_turn":
                    break
                # Server-side tool loop (web search) paused; resend to let it resume.
                messages = [messages[0], {"role": "assistant", "content": resp.content}]
        except anthropic.AuthenticationError as e:
            raise LLMError(f"Authentication failed — check ANTHROPIC_API_KEY ({e.message})") from e
        except anthropic.RateLimitError as e:
            raise LLMError(f"Rate limited by the API; try again shortly ({e.message})") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Could not reach the Claude API: {e}") from e

        if resp.stop_reason == "refusal":
            category = resp.stop_details.category if resp.stop_details else None
            raise LLMError(f"Claude declined the {task} request (category: {category})")
        if resp.stop_reason == "max_tokens":
            raise LLMError(f"{task}: response hit max_tokens; raise llm.max_tokens in config.yaml")
        if resp.parsed_output is None:
            raise LLMError(f"{task}: no structured output returned (stop_reason={resp.stop_reason})")
        return resp.parsed_output


class DryRunLLM:
    """Replays responses from samples/fixtures/<fixture_key>.json, keyed by task name."""

    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = fixtures_dir

    def parse(self, *, task: str, system: str, user: str, schema: type[T],
              tools: Optional[list[dict]] = None, fixture_key: Optional[str] = None) -> T:
        path = self.fixtures_dir / f"{fixture_key}.json"
        if not fixture_key or not path.exists():
            raise LLMError(
                f"--dry-run has no canned response for this posting ({fixture_key or 'no key'}). "
                "Dry-run only works on the bundled samples; set ANTHROPIC_API_KEY for real screening."
            )
        data = json.loads(path.read_text())
        if task not in data:
            raise LLMError(f"Fixture {path.name} has no '{task}' response")
        return schema.model_validate(data[task])
