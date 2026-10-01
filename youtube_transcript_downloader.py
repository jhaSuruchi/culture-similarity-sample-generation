#!/usr/bin/env python3
"""Download YouTube transcripts and preserve source-link provenance.

The script uses youtube-transcript-api and stores one transcript record per
video. It is resumable: existing records in the output JSONL are reused unless
--redownload is supplied. It downloads transcript text only, not video/audio.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "cultural_crawl_youtube" / "cultural_sources.json"
DEFAULT_OUT_DIR = ROOT / "cultural_crawl_youtube" / "transcripts"
FIELDS = [
    "record_id", "external_id", "source_link", "title", "language", "transcript_language",
    "transcript_type", "transcript", "transcript_segments_json", "download_status",
    "retrieved_at", "error",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_sources(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array of source records")
    return data


def video_id(source: dict[str, Any]) -> str:
    external_id = clean(source.get("external_id"))
    if external_id:
        return external_id
    parsed = urlparse(clean(source.get("url")))
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/").split("/")[0]
    return parse_qs(parsed.query).get("v", [""])[0]


def transcript_text_and_segments(transcript: Any) -> tuple[str, list[dict[str, Any]]]:
    segments: list[dict[str, Any]] = []
    for item in transcript:
        if hasattr(item, "text"):
            text = clean(item.text)
            start = getattr(item, "start", None)
            duration = getattr(item, "duration", None)
        else:
            text = clean(item.get("text"))
            start = item.get("start")
            duration = item.get("duration")
        if text:
            segments.append({"text": text, "start": start, "duration": duration})
    return " ".join(segment["text"] for segment in segments), segments


def fetch_transcript(video: str, languages: list[str]) -> tuple[str, str, str, list[dict[str, Any]]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError("install youtube-transcript-api: python3 -m pip install youtube-transcript-api") from exc

    api = YouTubeTranscriptApi()
    fetched = None
    selected_language = ""
    transcript_type = ""
    errors: list[str] = []

    # Current API: api.fetch(video_id, languages=[...]).
    try:
        fetched = api.fetch(video, languages=languages)
        selected_language = clean(getattr(fetched, "language_code", ""))
        transcript_type = "generated" if getattr(fetched, "is_generated", False) else "manual"
    except Exception as exc:
        errors.append(str(exc))

    # Older API compatibility: YouTubeTranscriptApi.get_transcript(...).
    if fetched is None and hasattr(YouTubeTranscriptApi, "get_transcript"):
        try:
            fetched = YouTubeTranscriptApi.get_transcript(video, languages=languages)
            selected_language = languages[0] if languages else ""
            transcript_type = "unknown"
        except Exception as exc:
            errors.append(str(exc))

    if fetched is None:
        raise RuntimeError("; ".join(errors[-2:]) or "transcript unavailable")
    text, segments = transcript_text_and_segments(fetched)
    if not text:
        raise RuntimeError("transcript was empty")
    return text, selected_language, transcript_type, segments


def write_outputs(rows: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcripts.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "transcripts.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out_dir / "transcripts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--languages", default="en,hi,sa,ne,si,zh,ja,ko,id,th,km,lo,my,ms,vi")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--redownload", action="store_true")
    args = parser.parse_args()

    sources = read_sources(args.source_file)
    sources = sources[:args.limit] if args.limit else sources
    languages = [value.strip() for value in args.languages.split(",") if value.strip()]
    manifest_path = args.out_dir / "transcripts.jsonl"
    existing = {}
    if manifest_path.exists() and not args.redownload:
        existing = {
            row["record_id"]: row
            for row in (json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip())
        }

    rows = []
    for index, source in enumerate(sources, 1):
        rid = clean(source.get("record_id"))
        if rid in existing:
            rows.append(existing[rid])
            continue
        source_link = clean(source.get("url"))
        vid = video_id(source)
        row = {
            "record_id": rid, "external_id": vid, "source_link": source_link,
            "title": clean(source.get("title")), "language": clean(source.get("language")),
            "transcript_language": "", "transcript_type": "", "transcript": "",
            "transcript_segments_json": "", "download_status": "", "retrieved_at": now(), "error": "",
        }
        try:
            if not vid:
                raise RuntimeError("could not determine YouTube video ID")
            text, transcript_language, transcript_type, segments = fetch_transcript(vid, languages)
            row.update(
                transcript_language=transcript_language, transcript_type=transcript_type,
                transcript=text, transcript_segments_json=json.dumps(segments, ensure_ascii=False),
                download_status="downloaded",
            )
        except Exception as exc:
            row.update(download_status="error", error=str(exc))
        rows.append(row)
        write_outputs(rows, args.out_dir)
        print(f"[{index}/{len(sources)}] {rid} {row['download_status']}", flush=True)
        time.sleep(max(0, args.sleep))

    write_outputs(rows, args.out_dir)
    downloaded = sum(row["download_status"] == "downloaded" for row in rows)
    failed = sum(row["download_status"] == "error" for row in rows)
    print(f"Processed {len(rows)} sources; transcripts downloaded={downloaded}; failed={failed}; output={args.out_dir}")


if __name__ == "__main__":
    main()
