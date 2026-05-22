"""Stage 2 tagger — calls Claude to assign structured tags to signals.

The tagger is part of the frozen engine surface (DESIGN.md §3). The agent
tunes prompts/tagging.md (the semantic contract — what each tag means)
and pipeline.yaml (model, batch_size, temperature, max_tokens). The
batching mechanics, retry/parse logic, and resume-from-tagged behavior
live here.

LLM calls go through llm.py, which shells out to `claude -p`. No
ANTHROPIC_API_KEY needed; auth lives in Claude Code.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from llm import Anthropic, APIError


# Tagger appends this to prompts/tagging.md so the same prompt file can
# describe the per-signal semantics while the engine controls batching.
BATCH_INSTRUCTION = (
    "Tag the following {n} signals using the rules above. "
    "Return ONE entry per input signal, in the same order, inside the "
    "`tagged:` YAML list. Quote substrings MUST appear verbatim in the "
    "signal's raw_text."
)


def tag_signals(config: dict, rdir: Path) -> None:
    """Tag every signal under rdir/signals/ that doesn't already have a tag file."""
    tcfg = config.get("tagging") or {}
    prompt_file = tcfg.get("prompt_file", "prompts/tagging.md")
    batch_size = int(tcfg.get("batch_size", 15))
    model = tcfg.get("model", "claude-sonnet-4-6")
    temperature = float(tcfg.get("temperature", 0.2))
    max_tokens = int(tcfg.get("max_tokens", 8192))

    semantic_prompt = Path(prompt_file).read_text()

    signals_dir = rdir / "signals"
    tags_dir = rdir / "tags"
    tags_dir.mkdir(parents=True, exist_ok=True)

    all_signals = sorted(signals_dir.glob("*/sig_*.yaml"))
    if not all_signals:
        print("  no signals in this run; run `prospect run --stages ingest` first")
        return

    already_tagged = {p.stem for p in tags_dir.glob("sig_*.yaml")}
    pending = [p for p in all_signals if p.stem not in already_tagged]
    if not pending:
        print(f"  all {len(all_signals)} signals already tagged")
        return

    print(f"  tagging {len(pending)} signals in batches of {batch_size} ({model})")

    client = Anthropic()
    batches = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
    total_tagged = 0

    for bi, batch in enumerate(batches, 1):
        records = [_load_signal(p) for p in batch]
        user_msg = _build_message(semantic_prompt, records)
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": user_msg}],
            )
        except APIError as e:
            print(f"    batch {bi}/{len(batches)}: API error: {e}; skipping")
            continue

        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        try:
            parsed = _extract_yaml(text)
        except ValueError as e:
            print(f"    batch {bi}/{len(batches)}: parse failed ({e}); first 200 chars: {text[:200]!r}")
            continue

        wrote = 0
        for tagged in parsed.get("tagged") or []:
            sid = tagged.get("signal_id")
            if not sid:
                continue
            with (tags_dir / f"{sid}.yaml").open("w") as f:
                yaml.safe_dump(tagged, f, sort_keys=False, allow_unicode=True)
            wrote += 1
        total_tagged += wrote
        print(f"    batch {bi}/{len(batches)}: tagged {wrote}/{len(batch)}")

    print(f"  total tagged this run: {total_tagged}/{len(pending)}")


def _load_signal(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _build_message(semantic_prompt: str, records: list[dict]) -> str:
    blocks = []
    for r in records:
        text = (r.get("raw_text") or "").strip()
        # Indent for block-scalar; cap raw_text at ~6KB per signal so we don't
        # blow past the model's context with one huge HN comment.
        if len(text) > 6000:
            text = text[:6000] + "\n  …[truncated]"
        indented = "\n".join("  " + line for line in text.splitlines())
        blocks.append(
            f"---\n"
            f"signal_id: {r.get('signal_id', 'unknown')}\n"
            f"source_platform: {r.get('source_platform', '')}\n"
            f"source_context: {r.get('source_context', '')}\n"
            f"raw_text: |\n{indented}"
        )
    return (
        semantic_prompt
        + "\n\n---\n\n"
        + BATCH_INSTRUCTION.format(n=len(records))
        + "\n\n"
        + "\n".join(blocks)
    )


_YAML_FENCE = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)


def _extract_yaml(text: str) -> dict:
    m = _YAML_FENCE.search(text)
    body = m.group(1) if m else text
    parsed = yaml.safe_load(body)
    if not isinstance(parsed, dict):
        raise ValueError("expected mapping at top level")
    return parsed
