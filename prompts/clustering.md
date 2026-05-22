# Clustering prompt — Stage 3

## Task

You are labelling and summarizing clusters produced by HDBSCAN over signal
embeddings. For each cluster you are given the 5 signals closest to its
centroid (the "representatives"). Produce a one-line label and a 2–3
sentence summary that describe the SINGLE underlying problem these signals
share.

## Inputs

```yaml
cluster_id: clust_017
representatives:
  - signal_id: sig_a1b2c3d4
    raw_text: |
      We spend 3 hours every Friday manually compiling engineering metrics…
  - signal_id: sig_e5f6g7h8
    raw_text: |
      How do you know if your code review process is actually working?
  # … 3 more …
```

## Output format

```yaml
cluster_id: clust_017
cluster_label: "Engineering teams lack visibility into code review bottlenecks"
cluster_summary: |
  Engineering managers and team leads can't measure whether code review
  is getting better or worse. They build spreadsheet workarounds, export
  data from GitHub/GitLab manually, or just guess.
```

## Rules

- If the 5 signals do NOT describe a single underlying problem, return
  `cluster_label: INCOHERENT` and explain in the summary which two or
  three distinct problems are mixed together. Do not invent a label that
  papers over the incoherence — the coherence auditor will catch it.
- The label is a noun phrase, not a product pitch. Describe the pain,
  not the imagined solution.
- The summary should be readable by someone who has never seen the
  signals — name the buyer persona and what they currently do about it.

## Examples

<!-- Agent adds examples here as the clustering pipeline matures. -->
