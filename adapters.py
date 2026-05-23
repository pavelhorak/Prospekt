"""Source adapters for Stage 1 (Ingest).

Each adapter is a function that yields normalized Signal records from
one platform. Adapters are part of the frozen engine surface
(DESIGN.md §3 — "the agent cannot change prospect.py, the pipeline
engine, or source adapters") and live here so prospect.py stays
focused on orchestration, metrics, and the CLI.

Currently wired (zero-config, free):
  hackernews     — Algolia search + Firebase item endpoint
  stackoverflow  — Stack Exchange API (10k req/day unauth)
  github_issues  — REST search; honors GH_TOKEN env var when present
  google_trends  — via trendspy; gracefully skips if not installed
                   (pytrends was replaced after Google's 2024-2025 backend
                   changes returned HTTP 400 on every query)
  reddit         — application-only OAuth (REDDIT_CLIENT_ID +
                   REDDIT_CLIENT_SECRET env vars; create a "web app" at
                   reddit.com/prefs/apps). Soft-skips when creds missing.

Adapters honor `seen_urls` for cross-run dedup by source_url
(DESIGN.md §7 Stage 1 contract).
"""

from __future__ import annotations

import datetime as _dt
import os
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from typing import Iterable

import requests

UA = "prospect/0.1 (+https://github.com/pavelhorak/Prospekt)"
TIMEOUT = 30


@dataclass
class Signal:
    signal_id: str
    raw_text: str
    source_platform: str
    source_url: str
    source_context: str
    author_info: str | None = None
    engagement: dict = field(default_factory=dict)
    date_posted: str | None = None
    date_collected: str = ""
    collection_query: str = ""
    structured: dict = field(default_factory=dict)
    attachments: list = field(default_factory=list)


def new_signal_id() -> str:
    return "sig_" + uuid.uuid4().hex[:12]


def _today() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _get_json(url: str, params: dict | None = None, headers: dict | None = None, retries: int = 3) -> dict:
    h = {"User-Agent": UA, **(headers or {})}
    backoff = 1.0
    last = None
    for _ in range(retries):
        r = requests.get(url, params=params, headers=h, timeout=TIMEOUT)
        last = r
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 503):
            time.sleep(backoff)
            backoff *= 2
            continue
        r.raise_for_status()
    if last is not None:
        last.raise_for_status()
    return {}


# ---------------------------------------------------------------------------
# Hacker News (Algolia search + Firebase item endpoint)
# ---------------------------------------------------------------------------

HN_ALGOLIA = "https://hn.algolia.com/api/v1/search"
HN_FIREBASE = "https://hacker-news.firebaseio.com/v0/item"


def fetch_hackernews(config: dict, seen_urls: set[str]) -> Iterable[Signal]:
    queries = config.get("queries", [])
    max_per_query = int(config.get("max_per_query", 30))
    include_comments = int(config.get("top_comments_per_story", 3))
    today = _today()

    for q in queries:
        data = _get_json(HN_ALGOLIA, params={
            "query": q,
            "tags": "story",
            "hitsPerPage": max_per_query,
        })
        for hit in data.get("hits", []):
            story_id = hit.get("objectID")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
            if url in seen_urls:
                continue
            title = hit.get("title") or ""
            text = hit.get("story_text") or ""
            yield Signal(
                signal_id=new_signal_id(),
                raw_text=(title + "\n\n" + text).strip(),
                source_platform="hackernews",
                source_url=url,
                source_context="HN Story",
                author_info=hit.get("author"),
                engagement={
                    "points": hit.get("points", 0),
                    "num_comments": hit.get("num_comments", 0),
                },
                date_posted=(hit.get("created_at") or "")[:10] or None,
                date_collected=today,
                collection_query=f"hn algolia: {q}",
            )
            seen_urls.add(url)
            if include_comments > 0 and story_id:
                item = _get_json(f"{HN_FIREBASE}/{story_id}.json")
                for kid in (item or {}).get("kids", [])[:include_comments]:
                    c = _get_json(f"{HN_FIREBASE}/{kid}.json")
                    if not c or c.get("deleted") or c.get("dead") or not c.get("text"):
                        continue
                    # Strip [dead] / [flagged] moderation placeholders that
                    # slip past the API's `deleted`/`dead` flags.
                    text_lower = c["text"].strip().lower()
                    if text_lower in ("[dead]", "[flagged]") or text_lower.startswith("[dead]") and len(text_lower) < 40:
                        continue
                    curl = f"https://news.ycombinator.com/item?id={kid}"
                    if curl in seen_urls:
                        continue
                    posted = None
                    if c.get("time"):
                        posted = _dt.datetime.fromtimestamp(c["time"], _dt.timezone.utc).date().isoformat()
                    yield Signal(
                        signal_id=new_signal_id(),
                        raw_text=c["text"],
                        source_platform="hackernews",
                        source_url=curl,
                        source_context=f"HN Comment on story {story_id}",
                        author_info=c.get("by"),
                        engagement={"parent": story_id},
                        date_posted=posted,
                        date_collected=today,
                        collection_query=f"hn comments under: {q}",
                    )
                    seen_urls.add(curl)
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# Stack Overflow (Stack Exchange API)
# ---------------------------------------------------------------------------

SO_URL = "https://api.stackexchange.com/2.3/search/advanced"


def fetch_stackoverflow(config: dict, seen_urls: set[str]) -> Iterable[Signal]:
    queries = config.get("queries", [])
    tags = config.get("tags", [])
    max_per_query = int(config.get("max_per_query", 30))
    today = _today()

    for q in queries:
        params = {
            "order": "desc",
            "sort": "votes",
            "q": q,
            "site": "stackoverflow",
            "pagesize": max_per_query,
            "filter": "withbody",
        }
        if tags:
            params["tagged"] = ";".join(tags)
        data = _get_json(SO_URL, params=params)
        for item in data.get("items", []):
            url = item.get("link")
            if not url or url in seen_urls:
                continue
            posted = None
            if item.get("creation_date"):
                posted = _dt.datetime.fromtimestamp(item["creation_date"], _dt.timezone.utc).date().isoformat()
            yield Signal(
                signal_id=new_signal_id(),
                raw_text=(item.get("title", "") + "\n\n" + item.get("body", "")).strip(),
                source_platform="stackoverflow",
                source_url=url,
                source_context=f"SO question (tags: {', '.join(item.get('tags', []))})",
                author_info=(item.get("owner") or {}).get("display_name"),
                engagement={
                    "score": item.get("score", 0),
                    "view_count": item.get("view_count", 0),
                    "answer_count": item.get("answer_count", 0),
                    "is_answered": item.get("is_answered", False),
                },
                date_posted=posted,
                date_collected=today,
                collection_query=f"stackoverflow: {q}" + (f" tags={tags}" if tags else ""),
                structured={"tags": item.get("tags", [])},
            )
            seen_urls.add(url)
        if data.get("backoff"):
            time.sleep(int(data["backoff"]))


# ---------------------------------------------------------------------------
# GitHub Issues
# ---------------------------------------------------------------------------

GH_SEARCH = "https://api.github.com/search/issues"


def fetch_github_issues(config: dict, seen_urls: set[str]) -> Iterable[Signal]:
    queries = config.get("queries", [])
    max_per_query = int(config.get("max_per_query", 30))
    today = _today()
    token = os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for q in queries:
        try:
            data = _get_json(GH_SEARCH, params={"q": q, "per_page": max_per_query}, headers=headers)
        except requests.HTTPError as e:
            print(f"  github_issues: query failed ({e}); set GH_TOKEN for higher limits")
            continue
        for issue in data.get("items", []):
            url = issue.get("html_url")
            if not url or url in seen_urls:
                continue
            repo = (issue.get("repository_url") or "").replace("https://api.github.com/repos/", "")
            yield Signal(
                signal_id=new_signal_id(),
                raw_text=(issue.get("title", "") + "\n\n" + (issue.get("body") or "")).strip(),
                source_platform="github_issues",
                source_url=url,
                source_context=f"GitHub issue in {repo}" if repo else "GitHub issue",
                author_info=(issue.get("user") or {}).get("login"),
                engagement={
                    "comments": issue.get("comments", 0),
                    "reactions": (issue.get("reactions") or {}).get("total_count", 0),
                    "state": issue.get("state"),
                },
                date_posted=(issue.get("created_at") or "")[:10] or None,
                date_collected=today,
                collection_query=f"github issues: {q}",
                structured={
                    "labels": [l.get("name") for l in issue.get("labels", [])],
                    "is_pull_request": "pull_request" in issue,
                    "repo": repo,
                },
            )
            seen_urls.add(url)
        # Search API: 30 req/min unauth, 30/min auth. Sleep to stay safe.
        time.sleep(2.0 if not token else 1.0)


# ---------------------------------------------------------------------------
# Google Trends (via pytrends — optional dependency)
# ---------------------------------------------------------------------------

GOOGLE_REFERER = {"referer": "https://www.google.com/"}


def fetch_google_trends(config: dict, seen_urls: set[str]) -> Iterable[Signal]:
    try:
        from trendspy import Trends
    except ImportError:
        print("  google_trends: trendspy not installed; skipping. `pip install trendspy`")
        return
    keywords = config.get("keywords", [])
    timeframe = config.get("timeframe", "today 24-m")
    geo = config.get("geo", "")
    today = _today()
    # request_delay=2.0 dodges Google's per-IP soft rate limit; without it the
    # third or fourth keyword reliably 429s. trendspy itself recommends this.
    tr = Trends(request_delay=2.0)

    for kw in keywords:
        try:
            df = tr.interest_over_time([kw], timeframe=timeframe, geo=geo or "")
        except Exception as e:
            print(f"  google_trends: '{kw}' interest_over_time failed: {e}")
            continue
        if df is None or df.empty or kw not in df.columns:
            continue

        # related_queries is the brittle endpoint; degrade gracefully on failure.
        related_top: list[str] = []
        related_rising: list[str] = []
        try:
            rq = tr.related_queries(kw, headers=GOOGLE_REFERER) or {}
            top_df = rq.get("top")
            rising_df = rq.get("rising")
            if top_df is not None and "query" in getattr(top_df, "columns", []):
                related_top = list(top_df["query"][:10])
            if rising_df is not None and "query" in getattr(rising_df, "columns", []):
                related_rising = list(rising_df["query"][:10])
        except Exception as e:
            print(f"  google_trends: '{kw}' related_queries soft-fail: {e}")

        series = [[d.strftime("%Y-%m-%d"), int(v)] for d, v in df[kw].items()]
        if not series:
            continue
        first = next((v for _, v in series if v), 0)
        last = series[-1][1]
        slope_pct = ((last - first) / first * 100.0) if first else 0.0
        peak = int(df[kw].max())
        url = f"https://trends.google.com/trends/explore?q={urllib.parse.quote(kw)}"
        if url in seen_urls:
            continue

        yield Signal(
            signal_id=new_signal_id(),
            raw_text=(
                f"Google Trends interest for '{kw}' from {series[0][0]} to {series[-1][0]} "
                f"(timeframe={timeframe}, geo={geo or 'global'}). "
                f"Peak relative interest {peak}/100; change start-to-end {slope_pct:+.0f}%. "
                + (f"Top related queries: {', '.join(related_top[:5])}." if related_top else "")
            ).strip(),
            source_platform="google_trends",
            source_url=url,
            source_context=f"Google Trends, timeframe={timeframe}, geo={geo or 'global'}",
            engagement={"slope_pct": round(slope_pct, 1), "peak": peak},
            date_posted=series[-1][0],
            date_collected=today,
            collection_query=f"google trends: {kw}",
            structured={
                "keyword": kw,
                "timeframe": timeframe,
                "geo": geo,
                "series": series,
                "related_top": related_top,
                "related_rising": related_rising,
            },
        )
        seen_urls.add(url)
        time.sleep(2.0)


# ---------------------------------------------------------------------------
# Reddit (application-only OAuth via client_credentials)
# ---------------------------------------------------------------------------

REDDIT_UA = "prospect/0.1 (open-source signals research; +https://github.com/pavelhorak/Prospekt)"


def fetch_reddit(config: dict, seen_urls: set[str]) -> Iterable[Signal]:
    cid = os.environ.get("REDDIT_CLIENT_ID")
    csec = os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not csec:
        print(
            "  reddit: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set; skipping.\n"
            "    Create a 'web app' at https://www.reddit.com/prefs/apps and export both."
        )
        return

    try:
        tok = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(cid, csec),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": REDDIT_UA},
            timeout=TIMEOUT,
        )
        tok.raise_for_status()
        token = tok.json()["access_token"]
    except Exception as e:
        print(f"  reddit: OAuth failed ({e}); skipping")
        return

    headers = {"User-Agent": REDDIT_UA, "Authorization": f"Bearer {token}"}
    subreddits = config.get("subreddits") or []
    queries = config.get("queries") or []
    sort = config.get("sort", "top")
    time_filter = config.get("time_filter", "year")
    max_per_query = int(config.get("max_per_query", 25))
    today = _today()

    for sr in subreddits:
        for q in queries:
            try:
                r = requests.get(
                    f"https://oauth.reddit.com/r/{sr}/search",
                    headers=headers,
                    params={
                        "q": q,
                        "restrict_sr": "true",
                        "sort": sort,
                        "t": time_filter,
                        "limit": max_per_query,
                    },
                    timeout=TIMEOUT,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                print(f"  reddit: r/{sr} q={q!r} failed: {e}; skipping")
                continue

            for child in (data.get("data") or {}).get("children", []):
                post = child.get("data") or {}
                permalink = post.get("permalink")
                if not permalink:
                    continue
                url = "https://reddit.com" + permalink
                if url in seen_urls:
                    continue
                created = post.get("created_utc")
                posted = None
                if created:
                    posted = _dt.datetime.fromtimestamp(created, _dt.timezone.utc).date().isoformat()
                title = post.get("title") or ""
                selftext = post.get("selftext") or ""
                yield Signal(
                    signal_id=new_signal_id(),
                    raw_text=(title + "\n\n" + selftext).strip(),
                    source_platform="reddit",
                    source_url=url,
                    source_context=f"r/{sr}",
                    author_info=post.get("author"),
                    engagement={
                        "score": post.get("score", 0),
                        "ups": post.get("ups", 0),
                        "num_comments": post.get("num_comments", 0),
                        "upvote_ratio": post.get("upvote_ratio"),
                    },
                    date_posted=posted,
                    date_collected=today,
                    collection_query=f"reddit r/{sr} q={q!r} sort={sort} t={time_filter}",
                    structured={
                        "subreddit": sr,
                        "link_flair_text": post.get("link_flair_text"),
                        "over_18": post.get("over_18", False),
                    },
                )
                seen_urls.add(url)
            time.sleep(1.5)  # Reddit OAuth: 60 req/min hard cap


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

ADAPTERS = {
    "hackernews":    fetch_hackernews,
    "stackoverflow": fetch_stackoverflow,
    "github_issues": fetch_github_issues,
    "google_trends": fetch_google_trends,
    "reddit":        fetch_reddit,
}
