"""Cold-context auditors for tag and cluster quality (DESIGN.md §4).

The auditor model MUST be different from the tagger/clusterer and is fed
ONLY the raw_text (no prior labels, no original prompt, no cluster
summary). It answers a single targeted question. Auditor config lives
under `audit:` in pipeline.yaml.

This file is part of the frozen engine surface — the autoresearch loop
cannot edit it. The agent tunes which dimensions get audited, sample
sizes, and the auditor model via pipeline.yaml.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

import yaml

from llm import Anthropic, APIError


_WORKAROUND_Q = (
    "Does this text describe a manual workaround, hack, spreadsheet, or script "
    "that someone built to compensate for missing software functionality? "
    "Answer ONLY 'yes' or 'no'."
)

_SPEND_Q = (
    "Does this text mention money spent on a software product, a budget for one, "
    "or a price someone is paying or considering paying? "
    "Answer ONLY 'yes' or 'no'."
)

_COHERENCE_Q_HEAD = (
    "Below are several short texts from the public internet. "
    "Do they all describe the SAME underlying problem (not merely the same topic, "
    "but the same actionable pain a single tool could address)? "
    "Rate 0–5 where 0 = unrelated, 5 = clearly one problem in different words. "
    "Answer with ONLY the number."
)


def _audit_client(audit_cfg: dict) -> Anthropic:
    return Anthropic()


def _ask_yes_no(client, model: str, temperature: float, question: str, raw_text: str) -> Optional[bool]:
    prompt = f"{question}\n\n---\n\n{raw_text[:4000]}"
    resp = client.messages.create(
        model=model,
        max_tokens=10,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip().lower()
    if txt.startswith("yes"):
        return True
    if txt.startswith("no"):
        return False
    return None


def audit_tag_precision(
    tags: list[dict],
    signals: list[dict],
    dimension: str,
    audit_cfg: dict,
    sample_size: Optional[int] = None,
) -> Optional[float]:
    """For tag dimension 'has_workaround' or 'has_spend' marked 'yes', sample N,
    ask the auditor model the corresponding yes/no. Returns precision in [0,1]
    or None if there are no positive examples to audit."""
    if dimension == "has_workaround":
        question = _WORKAROUND_Q
    elif dimension == "has_spend":
        question = _SPEND_Q
    else:
        raise ValueError(f"unsupported audit dimension: {dimension}")

    yes_signal_ids: list[str] = []
    for t in tags:
        sid = t.get("signal_id")
        if not sid:
            continue
        d = (t.get("tags") or {}).get(dimension)
        if isinstance(d, dict) and d.get("value") == "yes":
            yes_signal_ids.append(sid)

    if not yes_signal_ids:
        return None

    sigs_by_id = {s.get("signal_id"): s for s in signals}
    n = sample_size or int(audit_cfg.get("sample_size", 20))
    sample = random.sample(yes_signal_ids, min(n, len(yes_signal_ids)))
    model = audit_cfg.get("model", "claude-opus-4-7")
    temperature = float(audit_cfg.get("temperature", 0.0))
    client = _audit_client(audit_cfg)

    confirmed = 0
    rated = 0
    for sid in sample:
        sig = sigs_by_id.get(sid)
        if not sig or not sig.get("raw_text"):
            continue
        try:
            verdict = _ask_yes_no(client, model, temperature, question, sig["raw_text"])
        except APIError:
            continue
        if verdict is None:
            continue
        rated += 1
        if verdict:
            confirmed += 1
    if rated == 0:
        return None
    return confirmed / rated


def audit_cluster_coherence(
    clusters: list[dict],
    signals: list[dict],
    audit_cfg: dict,
    top_n: int = 10,
    n_signals: int = 5,
) -> Optional[float]:
    """For the top-N clusters by primary_signal_count, sample n_signals each;
    ask the auditor model to rate same-problem coherence 0–5. Returns average
    score normalized to [0,1], or None if no cluster could be rated."""
    if not clusters:
        return None

    sigs_by_id = {s.get("signal_id"): s for s in signals}
    top = sorted(
        clusters,
        key=lambda c: -(c.get("metrics") or {}).get("primary_signal_count", 0),
    )[:top_n]

    model = audit_cfg.get("model", "claude-opus-4-7")
    temperature = float(audit_cfg.get("temperature", 0.0))
    client = _audit_client(audit_cfg)

    scores: list[float] = []
    for c in top:
        primary = c.get("primary_signal_ids") or []
        if len(primary) < 2:
            continue
        pool = primary if len(primary) <= n_signals else random.sample(primary, n_signals)
        texts: list[str] = []
        for sid in pool:
            sig = sigs_by_id.get(sid)
            if sig and sig.get("raw_text"):
                texts.append(sig["raw_text"][:2000])
        if len(texts) < 2:
            continue
        prompt = _COHERENCE_Q_HEAD + "\n\n" + "\n\n---\n\n".join(texts)
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=10,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
        except APIError:
            continue
        txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        # Pull the first integer/float in the response
        for tok in txt.replace(",", " ").split():
            try:
                val = float(tok)
            except ValueError:
                continue
            scores.append(max(0.0, min(5.0, val)))
            break
    if not scores:
        return None
    return (sum(scores) / len(scores)) / 5.0
