"""Stage 3 clusterer — embed → HDBSCAN → merge → label → cross-assign → metrics.

Part of the frozen engine surface (DESIGN.md §3). The agent tunes
pipeline.yaml:clustering.* and prompts/clustering.md; the algorithm
contract, cluster_fingerprint formula, and metric computation live here.

Implements the DESIGN.md §7 Stage 3 contract:
- stratified representative selection (≤2 reps per source_platform)
- signal-to-centroid one-direction cross-assignment with a membership cap
- primary_signal_count vs total_signal_count separation
- temporal_trend from monthly bucket regression
- two source-diversity flavors (platform-level, context-level)
- cluster_fingerprint = sha256(sorted(top-3 central signal_ids))[:12]
- embedding_model recorded in clusters/index.yaml

Known failure modes documented in prospect.py:stage_cluster docstring
(style-based clustering, long-tail starvation, label hallucination,
cross-assignment runaway, embedding-model invalidation).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from llm import Anthropic, APIError

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover
    SentenceTransformer = None  # type: ignore

try:
    from sklearn.cluster import HDBSCAN
except ImportError:  # pragma: no cover
    HDBSCAN = None  # type: ignore


_YAML_FENCE = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)


def cluster_signals(config: dict, rdir: Path) -> None:
    _check_deps()
    ccfg = config.get("clustering") or {}
    embedding_model_name = ccfg.get("embedding_model", "all-MiniLM-L6-v2")
    min_cluster_size = int(ccfg.get("min_cluster_size", 3))
    min_samples = int(ccfg.get("min_samples", 2))
    merge_threshold = float(ccfg.get("merge_threshold", 0.85))
    cross_assign_threshold = float(ccfg.get("cross_assign_threshold", 0.70))
    membership_cap = int(ccfg.get("membership_cap", 3))
    prompt_file = ccfg.get("prompt_file", "prompts/clustering.md")
    label_model = ccfg.get("label_model") or (config.get("tagging") or {}).get("model", "claude-sonnet-4-6")
    label_temperature = float(ccfg.get("label_temperature", 0.2))

    signals_dir = rdir / "signals"
    clusters_dir = rdir / "clusters"
    clusters_dir.mkdir(parents=True, exist_ok=True)

    signal_files = sorted(signals_dir.glob("*/sig_*.yaml"))
    if not signal_files:
        print("  no signals; run `prospect run --stages ingest` first")
        return
    signals = [_load_yaml(p) for p in signal_files]
    tags = _load_tags(rdir, signals)  # dict signal_id -> tag dict (may be empty)
    has_tags = any(tags.values())
    print(f"  loaded {len(signals)} signals" + (f" with tags for {sum(1 for t in tags.values() if t)}" if has_tags else " (no tags found; tag-dependent metrics will be omitted)"))

    print(f"  embedding ({embedding_model_name})...")
    embeddings = _embed(signals, embedding_model_name, rdir / ".cache")
    # Normalize so cosine = dot product downstream
    embeddings = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-9)

    print(f"  HDBSCAN (min_cluster_size={min_cluster_size}, min_samples={min_samples})...")
    labels = _hdbscan(embeddings, min_cluster_size, min_samples)
    n_raw = len(set(labels) - {-1})
    n_orphans = int((labels == -1).sum())
    print(f"    {n_raw} raw clusters, {n_orphans} orphans")

    labels, centroids = _merge_clusters(embeddings, labels, merge_threshold)
    print(f"    {len(centroids)} clusters after merging at cosine > {merge_threshold}")

    primary_by_cluster: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels):
        if lab >= 0:
            primary_by_cluster[lab].append(i)

    print(f"  labeling {len(centroids)} clusters via {label_model}...")
    prompt_template = Path(prompt_file).read_text()
    client = Anthropic()
    label_records: dict[int, dict] = {}
    for cid in sorted(centroids.keys()):
        reps = _select_reps(signals, embeddings, primary_by_cluster[cid], centroids[cid], n=5)
        label_records[cid] = _llm_label(client, label_model, label_temperature, prompt_template, reps)

    print(f"  cross-assigning (threshold={cross_assign_threshold}, cap={membership_cap})...")
    extra_memberships = _cross_assign(embeddings, labels, centroids, cross_assign_threshold, membership_cap)

    total_by_cluster: dict[int, list[int]] = {cid: list(idxs) for cid, idxs in primary_by_cluster.items()}
    for sig_idx, extras in extra_memberships.items():
        for cid in extras:
            if sig_idx not in total_by_cluster[cid]:
                total_by_cluster[cid].append(sig_idx)

    print("  computing metrics + emitting cluster files...")
    out_records = []
    for ordinal, cid in enumerate(sorted(centroids.keys())):
        record = _build_cluster_record(
            ordinal=ordinal,
            cluster_idx=cid,
            primary_indices=primary_by_cluster[cid],
            total_indices=total_by_cluster[cid],
            signals=signals,
            tags=tags,
            embeddings=embeddings,
            centroid=centroids[cid],
            embedding_model=embedding_model_name,
            label=label_records[cid],
        )
        out_records.append(record)
        with (clusters_dir / f"{record['cluster_id']}.yaml").open("w") as f:
            yaml.safe_dump(record, f, sort_keys=False, allow_unicode=True)

    n_incoherent = sum(1 for r in out_records if r["cluster_label"] == "INCOHERENT")
    index = {
        "run_id": rdir.name,
        "embedding_model": embedding_model_name,
        "min_cluster_size": min_cluster_size,
        "min_samples": min_samples,
        "merge_threshold": merge_threshold,
        "cross_assign_threshold": cross_assign_threshold,
        "membership_cap": membership_cap,
        "total_signals": len(signals),
        "n_clusters": len(centroids),
        "n_orphans": n_orphans,
        "n_incoherent": n_incoherent,
        "orphan_rate": round(n_orphans / max(len(signals), 1), 3),
        "cluster_size_distribution": dict(Counter(len(r["all_signal_ids"]) for r in out_records)),
        "label_model": label_model,
    }
    with (clusters_dir / "index.yaml").open("w") as f:
        yaml.safe_dump(index, f, sort_keys=False)

    print(f"  wrote {len(out_records)} clusters ({n_incoherent} INCOHERENT)")


# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

def _check_deps() -> None:
    missing = []
    if SentenceTransformer is None:
        missing.append("sentence-transformers")
    if HDBSCAN is None:
        missing.append("scikit-learn>=1.3")
    if not shutil.which("claude"):
        missing.append("claude CLI (install Claude Code)")
    if missing:
        raise RuntimeError(
            "stage_cluster missing dependencies: "
            + ", ".join(missing)
            + ". Install via `pip install -r requirements.txt` and ensure `claude` is in PATH."
        )


# ---------------------------------------------------------------------------
# Embedding (disk-cached by sha256 of raw_text)
# ---------------------------------------------------------------------------

def _embed(signals: list[dict], model_name: str, cache_dir: Path) -> np.ndarray:
    """Returns an (n_signals, dim) array. Cache key = sha256(raw_text[:4096])."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"embeddings__{model_name.replace('/', '_')}.npz"

    cached: dict[str, np.ndarray] = {}
    if cache_file.exists():
        z = np.load(cache_file)
        for k, v in zip(z["keys"], z["vectors"]):
            cached[str(k)] = v

    def _key(s: dict) -> tuple[str, str]:
        text = (s.get("raw_text") or "")[:4096]
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return h, text

    missing_keys: list[str] = []
    missing_texts: list[str] = []
    for s in signals:
        h, t = _key(s)
        if h not in cached:
            missing_keys.append(h)
            missing_texts.append(t)

    if missing_texts:
        model = SentenceTransformer(model_name)
        new_vecs = model.encode(
            missing_texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True
        )
        for k, v in zip(missing_keys, new_vecs):
            cached[k] = v.astype(np.float32)
        np.savez(
            cache_file,
            keys=np.array(list(cached.keys())),
            vectors=np.stack(list(cached.values())),
        )

    dim = next(iter(cached.values())).shape[0]
    out = np.empty((len(signals), dim), dtype=np.float32)
    for i, s in enumerate(signals):
        h, _ = _key(s)
        out[i] = cached[h]
    return out


# ---------------------------------------------------------------------------
# HDBSCAN + merge
# ---------------------------------------------------------------------------

def _hdbscan(embeddings: np.ndarray, min_cluster_size: int, min_samples: int) -> np.ndarray:
    # Sklearn's HDBSCAN. Cosine metric isn't supported directly; we use
    # euclidean on normalized vectors (equivalent ranking).
    clusterer = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    return clusterer.fit_predict(embeddings)


def _merge_clusters(
    embeddings: np.ndarray, labels: np.ndarray, threshold: float
) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """Greedy merge: while the most-similar centroid pair exceeds threshold, merge."""
    labels = labels.copy()
    centroids = _compute_centroids(embeddings, labels)
    while len(centroids) >= 2:
        cids = sorted(centroids)
        C = np.stack([centroids[c] for c in cids])
        sim = C @ C.T
        np.fill_diagonal(sim, -np.inf)
        i, j = np.unravel_index(int(np.argmax(sim)), sim.shape)
        if sim[i, j] < threshold:
            break
        keep, drop = cids[i], cids[j]
        labels[labels == drop] = keep
        del centroids[drop]
        # Recompute the surviving centroid only
        mask = labels == keep
        c = embeddings[mask].mean(axis=0)
        c /= np.linalg.norm(c) + 1e-9
        centroids[keep] = c
    return labels, centroids


def _compute_centroids(embeddings: np.ndarray, labels: np.ndarray) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    for cid in sorted(set(int(l) for l in labels) - {-1}):
        c = embeddings[labels == cid].mean(axis=0)
        c /= np.linalg.norm(c) + 1e-9
        out[cid] = c
    return out


# ---------------------------------------------------------------------------
# Representative selection (stratified per source_platform)
# ---------------------------------------------------------------------------

def _select_reps(
    signals: list[dict],
    embeddings: np.ndarray,
    member_indices: list[int],
    centroid: np.ndarray,
    n: int = 5,
) -> list[dict]:
    if not member_indices:
        return []
    sims = embeddings[member_indices] @ centroid
    order = np.argsort(-sims)

    selected: list[int] = []
    platform_count: dict[str, int] = defaultdict(int)
    for o in order:
        idx = member_indices[int(o)]
        platform = signals[idx].get("source_platform", "unknown")
        if platform_count[platform] < 2:
            selected.append(idx)
            platform_count[platform] += 1
            if len(selected) >= n:
                break

    if len(selected) < n:
        for o in order:
            idx = member_indices[int(o)]
            if idx in selected:
                continue
            selected.append(idx)
            if len(selected) >= n:
                break

    return [signals[i] for i in selected]


# ---------------------------------------------------------------------------
# LLM labeling
# ---------------------------------------------------------------------------

def _llm_label(
    client, model: str, temperature: float, prompt_template: str, reps: list[dict]
) -> dict:
    rep_block = ""
    for r in reps:
        text = (r.get("raw_text") or "").strip()
        if len(text) > 3000:
            text = text[:3000] + "\n[truncated]"
        indent = "\n".join("  " + line for line in text.splitlines())
        rep_block += (
            f"  - signal_id: {r.get('signal_id')}\n"
            f"    source_platform: {r.get('source_platform')}\n"
            f"    source_context: {r.get('source_context')}\n"
            f"    raw_text: |\n{indent}\n"
        )
    msg = (
        prompt_template
        + "\n\n---\n\n## Inputs\n\nrepresentatives:\n"
        + rep_block
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=temperature,
            messages=[{"role": "user", "content": msg}],
        )
    except APIError as e:
        return {"cluster_label": "ERROR", "cluster_summary": str(e), "method": "llm_error"}

    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    m = _YAML_FENCE.search(text)
    body = m.group(1) if m else text
    try:
        parsed = yaml.safe_load(body)
        if not isinstance(parsed, dict):
            raise ValueError("non-dict")
    except Exception as e:
        return {"cluster_label": "PARSE_ERROR", "cluster_summary": f"{e}: {text[:300]}", "method": "label_parse_failed"}

    return {
        "cluster_label": parsed.get("cluster_label", "UNLABELED"),
        "cluster_summary": parsed.get("cluster_summary", ""),
        "method": "llm",
    }


# ---------------------------------------------------------------------------
# Cross-assignment
# ---------------------------------------------------------------------------

def _cross_assign(
    embeddings: np.ndarray,
    labels: np.ndarray,
    centroids: dict[int, np.ndarray],
    threshold: float,
    cap: int,
) -> dict[int, list[int]]:
    """Returns {signal_idx: [extra_cluster_ids]}; cap extras at (cap - 1)."""
    cids = sorted(centroids)
    if not cids:
        return {}
    C = np.stack([centroids[c] for c in cids])  # already normalized
    sims = embeddings @ C.T  # embeddings already normalized
    extras: dict[int, list[int]] = {}
    for i in range(embeddings.shape[0]):
        primary = int(labels[i])
        candidates = [
            (float(sims[i, j]), cids[j])
            for j in range(len(cids))
            if cids[j] != primary and sims[i, j] > threshold
        ]
        candidates.sort(reverse=True)
        extras[i] = [cid for _, cid in candidates[: cap - 1]]
    return extras


# ---------------------------------------------------------------------------
# Per-cluster metrics + record construction
# ---------------------------------------------------------------------------

def _build_cluster_record(
    ordinal: int,
    cluster_idx: int,
    primary_indices: list[int],
    total_indices: list[int],
    signals: list[dict],
    tags: dict[str, dict],
    embeddings: np.ndarray,
    centroid: np.ndarray,
    embedding_model: str,
    label: dict,
) -> dict:
    cluster_id = f"clust_{ordinal:03d}"
    primary_sigs = [signals[i] for i in primary_indices]
    total_sigs = [signals[i] for i in total_indices]

    # Top-3 most central primary signals → cluster_fingerprint
    if primary_indices:
        sims = embeddings[primary_indices] @ centroid
        top3_order = np.argsort(-sims)[:3]
        top3_sids = sorted(primary_sigs[int(i)].get("signal_id", "") for i in top3_order)
    else:
        top3_sids = []
    fingerprint = hashlib.sha256(",".join(top3_sids).encode()).hexdigest()[:12]

    # Source diversity (platform vs context)
    platforms = sorted({s.get("source_platform") for s in total_sigs if s.get("source_platform")})
    contexts = {s.get("source_context") for s in total_sigs if s.get("source_context")}

    # Temporal trend
    dates = [s.get("date_posted") for s in total_sigs]
    trend = _temporal_trend([d for d in dates if d])

    metrics: dict[str, Any] = {
        "primary_signal_count": len(primary_indices),
        "total_signal_count": len(total_indices),
        "source_diversity": len(platforms),
        "context_diversity": len(contexts),
        "sources": platforms,
        "temporal_trend": trend,
    }

    # Tag-dependent metrics; populated only when this run has tags
    tag_records = [tags.get(s.get("signal_id", "")) for s in total_sigs]
    tag_records = [t for t in tag_records if t]
    if tag_records:
        metrics["intensity_distribution"] = _histogram(_extract_tag(tag_records, "pain_intensity"))
        metrics["intensity_mean"] = _safe_mean(_extract_tag(tag_records, "pain_intensity"))
        metrics["industries"] = sorted({v for v in _extract_tag(tag_records, "industry") if v and v != "unknown"})
        metrics["industry_spread"] = len(metrics["industries"])
        metrics["workaround_count"] = sum(
            1 for t in tag_records if _truthy(_get_tag_value(t, "has_workaround"))
        )
        metrics["spend_evidence_count"] = sum(
            1 for t in tag_records if _truthy(_get_tag_value(t, "has_spend"))
        )
        # competitor mentions
        mention_counts: Counter = Counter()
        for t in tag_records:
            mentioned = (t.get("tags") or {}).get("existing_solution_mentioned") or []
            if isinstance(mentioned, list):
                mention_counts.update(m for m in mentioned if m)
        metrics["competitor_mentions"] = dict(mention_counts.most_common(20))

    return {
        "cluster_id": cluster_id,
        "cluster_label": label.get("cluster_label", "UNLABELED"),
        "cluster_summary": label.get("cluster_summary", ""),
        "cluster_fingerprint": fingerprint,
        "embedding_model": embedding_model,
        "method": "hdbscan+merge+llm_label",
        "label_method": label.get("method", "llm"),
        "primary_signal_ids": [signals[i].get("signal_id") for i in primary_indices],
        "all_signal_ids": [signals[i].get("signal_id") for i in total_indices],
        "metrics": metrics,
    }


def _temporal_trend(dates_iso: list[str]) -> str:
    parsed = []
    for d in dates_iso:
        try:
            parsed.append(_dt.date.fromisoformat(d))
        except (ValueError, TypeError):
            continue
    if len(parsed) < 6:
        return "unknown"
    earliest, latest = min(parsed), max(parsed)
    if (latest - earliest).days < 180:
        return "unknown"
    buckets: Counter = Counter()
    for d in parsed:
        buckets[(d.year, d.month)] += 1
    if len(buckets) < 3:
        return "unknown"
    sorted_keys = sorted(buckets)
    counts = [buckets[k] for k in sorted_keys]
    n = len(counts)
    x_mean = (n - 1) / 2
    y_mean = sum(counts) / n
    num = sum((i - x_mean) * (c - y_mean) for i, c in enumerate(counts))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0 or y_mean == 0:
        return "unknown"
    slope_pct = (num / den) / y_mean * 100
    if slope_pct > 5:
        return "increasing"
    if slope_pct < -5:
        return "decreasing"
    return "stable"


def _extract_tag(tag_records: list[dict], dim: str) -> list:
    out = []
    for t in tag_records:
        v = _get_tag_value(t, dim)
        if v is not None:
            out.append(v)
    return out


def _get_tag_value(tag_record: dict, dim: str):
    tags = tag_record.get("tags") or {}
    entry = tags.get(dim)
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _truthy(v) -> bool:
    """Treat True/'yes'/'y'/'true' as yes; False/'no'/null/'unknown' as no.

    The tagging prompt asks for `yes`/`no` but YAML's unquoted `yes`/`no`
    parse to Python booleans True/False. Both representations need to count.
    """
    if v is True:
        return True
    if v is False or v is None:
        return False
    if isinstance(v, str):
        return v.strip().lower() in {"yes", "y", "true"}
    return False


def _histogram(values: list) -> dict:
    h: Counter = Counter()
    for v in values:
        if isinstance(v, (int, float)):
            h[int(v)] += 1
    return {k: h[k] for k in sorted(h)}


def _safe_mean(values: list) -> float | None:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    return round(sum(nums) / len(nums), 2) if nums else None


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _load_tags(rdir: Path, signals: list[dict]) -> dict[str, dict]:
    tags_dir = rdir / "tags"
    out: dict[str, dict] = {}
    if not tags_dir.exists():
        return out
    for s in signals:
        sid = s.get("signal_id")
        if not sid:
            continue
        p = tags_dir / f"{sid}.yaml"
        if p.exists():
            try:
                out[sid] = _load_yaml(p)
            except Exception:
                continue
    return out
