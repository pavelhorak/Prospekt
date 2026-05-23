"""llm.py — drop-in replacement for the anthropic SDK that routes through
the `claude` CLI (Claude Code) so the pipeline runs on the user's Claude
Code subscription instead of a paid Anthropic API key.

Surface compatible with how tagger.py, clusterer.py, enricher.py,
scorer.py, and auditor.py use anthropic:

    from llm import Anthropic, APIError
    client = Anthropic()                           # no api_key needed
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",             # mapped to "sonnet"
            max_tokens=4096,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
            tools=[...],                           # passed through; Claude Code
                                                   # ignores API-style tool defs
                                                   # and uses its own native tools
        )
    except APIError as e:
        ...
    text = "".join(b.text for b in resp.content if b.type == "text")

Implementation notes:
- Each `messages.create` shells out to `claude -p` and reads stdout.
- Runs from a temp cwd so Claude Code doesn't auto-load the project's
  CLAUDE.md, hooks, or memory files into every pipeline call.
- Per-call latency is the subprocess startup (~1-2s) plus model thinking.
- web_search: don't pass API-style tool blocks; the prompt itself should
  ask the model to "search the web" — Claude Code's native WebSearch
  tool is enabled via --allowed-tools WebSearch.
- Cost is billed to Claude Code, not direct API.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any


_MODEL_ALIASES = {
    "claude-sonnet-4-5": "sonnet",
    "claude-sonnet-4-6": "sonnet",
    "claude-sonnet-4-7": "sonnet",
    "claude-opus-4-5": "opus",
    "claude-opus-4-6": "opus",
    "claude-opus-4-7": "opus",
    "claude-haiku-4-5": "haiku",
    "claude-haiku-4-5-20251001": "haiku",
}


def _to_cli_model(model: str) -> str:
    if model in ("sonnet", "opus", "haiku"):
        return model
    return _MODEL_ALIASES.get(model, model)  # fall back to passing as-is


@dataclass
class TextBlock:
    text: str
    type: str = "text"
    citations: list = field(default_factory=list)


@dataclass
class Response:
    content: list[TextBlock]
    stop_reason: str = "end_turn"


class APIError(Exception):
    """Drop-in for anthropic.APIError used by the stage modules."""
    pass


class Anthropic:
    """Drop-in for anthropic.Anthropic that proxies to `claude -p`."""

    def __init__(self, api_key: str | None = None):
        # api_key is accepted for signature compatibility but ignored —
        # Claude Code handles auth via its own login (OAuth or env vars).
        if not shutil.which("claude"):
            raise RuntimeError(
                "claude CLI not found in PATH. Install Claude Code from "
                "https://claude.com/claude-code, or set llm_backend: api "
                "in pipeline.yaml to use the anthropic SDK directly."
            )
        self.messages = _Messages()


class _Messages:
    def create(
        self,
        *,
        model: str,
        messages: list,
        max_tokens: int | None = None,
        temperature: float | None = None,
        system: str | None = None,
        tools: list | None = None,
        json_schema: dict | None = None,
        **_kwargs: Any,
    ) -> Response:
        # Collapse the messages list into a single user prompt. The stage
        # modules pass a single user message; multi-turn isn't used.
        prompt_parts: list[str] = []
        for m in messages:
            content = m.get("content")
            if isinstance(content, str):
                prompt_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        prompt_parts.append(block.get("text", ""))
        prompt = "\n".join(prompt_parts)

        cli_model = _to_cli_model(model)
        # WebSearch is always allowed (enricher needs it; tagger/scorer
        # won't use it because their prompts don't require web data).
        # All other tools are blocked so a stray model can't shell out
        # to Bash/Read/Write on the user's machine.
        cmd = [
            "claude", "-p",
            "--model", cli_model,
            "--output-format", "text",
            "--permission-mode", "bypassPermissions",
            "--no-session-persistence",
            "--allowed-tools", "WebSearch",
        ]
        if system:
            cmd.extend(["--append-system-prompt", system])
        if json_schema:
            # --json-schema enforces schema-valid JSON output. The model
            # cannot mix prose with JSON or break the structure. Used by
            # enricher + scorer where free-form YAML was failing to parse.
            cmd.extend(["--json-schema", json.dumps(json_schema)])

        timeout = int(os.environ.get("CLAUDE_TIMEOUT_SEC", "900"))
        # Run from a clean tempdir so Claude Code doesn't auto-load the
        # project's CLAUDE.md, hooks, or memory into every call.
        with tempfile.TemporaryDirectory(prefix="prospect-claude-") as tmp:
            try:
                result = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=tmp,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise APIError(f"claude CLI timed out after {timeout}s")
            except FileNotFoundError:
                raise APIError("claude CLI vanished mid-flight")

        if result.returncode != 0:
            raise APIError(
                f"claude exited {result.returncode}: {result.stderr[:1500].strip()}"
            )

        return Response(content=[TextBlock(text=result.stdout)])
