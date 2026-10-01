#!/usr/bin/env python3
"""Crawl YouTube video metadata for the SETU-Culture research queries.

This crawler uses the YouTube Data API v3 search index and follows pagination
for every configured query. It stores video metadata as source records; it
does not download video or audio and does not classify YouTube as a discovery
mode.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "cultural_crawl_config.json"
DEFAULT_OUT_DIR = ROOT / "youtube_crawl_outputs"
API_ROOT = "https://www.googleapis.com/youtube/v3"
SOURCE_ID = "youtube_videos"
SOURCE_NAME = "YouTube videos"
SOURCE_TYPE = "youtube"
EVIDENCE_CLASS = "popular_secondary_material"
SOURCE_TIER = 0
RIGHTS_LICENSE = "varies_by_video_check_rights"
ACCESS_LEVEL = "metadata_only"
FIELDS = [
    "record_id", "source_id", "source_name", "source_type", "evidence_class", "source_tier",
    "title", "url", "description", "authors", "publisher", "publication_date", "language",
    "query_id", "query_group", "topic_query", "target_cultures", "seed_pair_id",
    "configured_relationship_type", "configured_shared_element", "seed_notes", "matched_queries_json",
    "domains", "rights_license", "access_level", "external_id", "retrieved_at",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(clean(item) for item in value if item not in (None, ""))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def build_queries(config: dict[str, Any], groups: set[str]) -> list[dict[str, Any]]:
    scope = config.get("geographic_scope", [])
    queries: list[dict[str, Any]] = []
    if "cross_cultural" in groups:
        for index, text in enumerate(config.get("cross_cultural_queries", []), 1):
            queries.append({
                "id": f"cross_{index:03d}", "group": "cross_cultural", "text": text,
                "cultures": [g["name"] for g in scope if re.search(rf"\b{re.escape(g['name'])}\b", text, re.I)],
            })
    if "seed_pairs" in groups:
        for seed in config.get("seed_pairs", []):
            text = clean(
                f"{seed.get('culture_a', {}).get('query', '')} "
                f"{seed.get('culture_b', {}).get('query', '')} "
                f"{seed.get('shared_element', '')} transmission adaptation similarity differences origin"
            )
            queries.append({
                "id": f"seed_{seed['id']}", "group": "seed_pairs", "text": text, "cultures": [],
                "seed_pair_id": seed["id"], "relationship_type": seed.get("relationship_type", ""),
                "shared_element": seed.get("shared_element", ""), "notes": seed.get("notes", ""),
            })
    if "geographic_pairs" in groups:
        for geographic in scope:
            if geographic["name"] == "India":
                continue
            for concept in config.get("query_concepts", []):
                queries.append({
                    "id": f"geo_{len(queries):04d}", "group": "geographic_pairs",
                    "text": f"India {geographic['name']} {concept} cultural transmission similarity differences shared origin adaptation",
                    "cultures": ["India", geographic["name"]],
                })
    if "local_context" in groups:
        for geographic in scope:
            for index, text in enumerate(geographic.get("local_queries", []), 1):
                queries.append({
                    "id": f"local_{geographic['name'].lower()}_{index}", "group": "local_context",
                    "text": f"{text} cross-cultural transmission adaptation comparison",
                    "cultures": [geographic["name"]],
                })
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for query in queries:
        key = query["text"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def api_get(endpoint: str, api_key: str, params: dict[str, Any], retries: int = 4) -> dict[str, Any]:
    request_params = dict(params)
    request_params["key"] = api_key
    url = f"{API_ROOT}/{endpoint}?{urllib.parse.urlencode(request_params, doseq=True)}"
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "SETU-Culture-YouTube-Crawler/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"YouTube API HTTP {exc.code}: {body[:1000]}") from exc
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(min(20, 2**attempt))
    raise RuntimeError(f"YouTube API request failed: {last_error}")


def make_record(video: dict[str, Any], query: dict[str, Any]) -> dict[str, str]:
    snippet = video.get("snippet") or {}
    video_id = clean(video.get("id"))
    title = clean(snippet.get("title"))
    url = f"https://www.youtube.com/watch?v={video_id}"
    match = {
        "query_id": query["id"], "query_group": query["group"], "query": query["text"],
        "target_cultures": query.get("cultures", []), "seed_pair_id": query.get("seed_pair_id", ""),
    }
    record_id = hashlib.sha256(f"{SOURCE_ID}|{video_id}".encode()).hexdigest()[:24]
    details = video.get("contentDetails") or {}
    statistics = video.get("statistics") or {}
    description = clean(snippet.get("description"))
    metadata = {
        "channel_id": clean(snippet.get("channelId")),
        "category_id": clean(snippet.get("categoryId")),
        "duration": clean(details.get("duration")),
        "view_count": clean(statistics.get("viewCount")),
        "like_count": clean(statistics.get("likeCount")),
        "comment_count": clean(statistics.get("commentCount")),
    }
    description = clean(f"{description} YouTube metadata: {metadata}")[:50000]
    return {
        "record_id": record_id, "source_id": SOURCE_ID, "source_name": SOURCE_NAME,
        "source_type": SOURCE_TYPE, "evidence_class": EVIDENCE_CLASS, "source_tier": str(SOURCE_TIER),
        "title": title, "url": url, "description": description,
        "authors": clean(snippet.get("channelTitle")), "publisher": "YouTube",
        "publication_date": clean(snippet.get("publishedAt")),
        "language": clean(snippet.get("defaultLanguage") or snippet.get("defaultAudioLanguage")),
        "query_id": query["id"], "query_group": query["group"], "topic_query": query["text"],
        "target_cultures": clean(query.get("cultures", [])), "seed_pair_id": query.get("seed_pair_id", ""),
        "configured_relationship_type": query.get("relationship_type", ""),
        "configured_shared_element": query.get("shared_element", ""), "seed_notes": query.get("notes", ""),
        "matched_queries_json": json.dumps([match], ensure_ascii=False), "domains": clean(snippet.get("tags", [])),
        "rights_license": RIGHTS_LICENSE, "access_level": ACCESS_LEVEL, "external_id": video_id,
        "retrieved_at": now(),
    }


def write_outputs(rows: list[dict[str, str]], output_dir: Path, config_bytes: bytes, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "cultural_sources.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "cultural_sources.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (output_dir / "cultural_sources.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "crawl_config_snapshot.json").write_bytes(config_bytes)
    (output_dir / "crawl_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default=os.environ.get("YOUTUBE_API_KEY", ""))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--query-groups", default="cross_cultural,seed_pairs,geographic_pairs,local_context")
    parser.add_argument("--max-pages", type=int, default=0, help="maximum result pages per query; 0 follows all available pages")
    parser.add_argument("--max-results-per-page", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=0.2)
    args = parser.parse_args()
    if not args.api_key:
        parser.error("set YOUTUBE_API_KEY or pass --api-key")
    if not 1 <= args.max_results_per_page <= 50:
        parser.error("--max-results-per-page must be between 1 and 50")

    started = now()
    config_bytes = args.config.read_bytes()
    config = json.loads(config_bytes)
    groups = {group.strip() for group in args.query_groups.split(",") if group.strip()}
    queries = build_queries(config, groups)
    rows_by_video: dict[str, dict[str, str]] = {}
    errors: list[dict[str, str]] = []
    pages_crawled = 0
    search_items = 0
    detail_items = 0

    for query in queries:
        page_token = ""
        page_number = 0
        try:
            while True:
                page_number += 1
                if args.max_pages and page_number > args.max_pages:
                    break
                search_params: dict[str, Any] = {
                    "part": "snippet", "q": query["text"], "type": "video",
                    "maxResults": args.max_results_per_page,
                }
                if page_token:
                    search_params["pageToken"] = page_token
                search_result = api_get("search", args.api_key, search_params)
                pages_crawled += 1
                items = search_result.get("items", [])
                search_items += len(items)
                ids = [clean(item.get("id", {}).get("videoId")) for item in items]
                ids = [video_id for video_id in ids if video_id]
                if ids:
                    details = api_get(
                        "videos", args.api_key,
                        {"part": "snippet,contentDetails,statistics", "id": ",".join(ids)},
                    )
                    for video in details.get("items", []):
                        detail_items += 1
                        record = make_record(video, query)
                        existing = rows_by_video.get(record["external_id"])
                        if existing:
                            matches = json.loads(existing["matched_queries_json"]) + json.loads(record["matched_queries_json"])
                            existing["matched_queries_json"] = json.dumps(
                                list({(m["query_id"], m["query"]): m for m in matches}.values()), ensure_ascii=False
                            )
                        else:
                            rows_by_video[record["external_id"]] = record
                page_token = search_result.get("nextPageToken", "")
                if not page_token:
                    break
                time.sleep(max(0, args.sleep))
        except Exception as exc:
            errors.append({"query_id": query["id"], "query": query["text"], "error": str(exc)})

    rows = sorted(rows_by_video.values(), key=lambda row: (row["query_group"], row["title"].lower(), row["external_id"]))
    report = {
        "started_at": started, "finished_at": now(), "source_id": SOURCE_ID,
        "query_groups": sorted(groups), "query_count": len(queries), "pages_crawled": pages_crawled,
        "search_items_seen": search_items, "video_details_seen": detail_items,
        "record_count": len(rows), "errors": errors, "request_delay_seconds": args.sleep,
        "max_pages": args.max_pages, "max_results_per_page": args.max_results_per_page,
    }
    write_outputs(rows, args.out_dir, config_bytes, report)
    print(f"Collected {len(rows)} unique YouTube video records into {args.out_dir}")
    print(f"Queries: {len(queries)}; pages: {pages_crawled}; errors: {len(errors)}")


if __name__ == "__main__":
    main()
