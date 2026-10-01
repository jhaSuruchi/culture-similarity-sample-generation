#!/usr/bin/env python3
"""Download and locally extract English SETU-Culture source records.

Stage 1 only: this script downloads source content and creates a manifest. It
does not call an LLM, create source pairs, or generate benchmark questions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

CSV_LIMIT = 50 * 1024 * 1024
MANIFEST_FIELDS = [
    "record_id", "source_id", "source_name", "title", "original_url", "resolved_url",
    "local_document_path", "local_text_path", "content_type", "file_extension", "sha256",
    "bytes_downloaded", "download_status", "extraction_status", "http_status", "language",
    "evidence_class", "source_tier", "rights_license", "external_id", "retrieved_at", "error",
]


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "template"}: self.skip += 1
        elif not self.skip and tag.lower() in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}: self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "template"} and self.skip: self.skip -= 1
        elif not self.skip and tag.lower() in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr"}: self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip: self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", html.unescape("".join(self.parts)))).strip()


def now() -> str: return datetime.now(timezone.utc).isoformat()


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_sources(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(max(csv.field_size_limit(), CSV_LIMIT))
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as f: return list(csv.DictReader(f))
    if path.suffix.lower() == ".jsonl": return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    data = json.loads(path.read_text(encoding="utf-8")); return data if isinstance(data, list) else data.get("records", data.get("sources", []))


def read_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists(): return {}
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8")); return {x["record_id"]: x for x in data}
    with path.open(encoding="utf-8", newline="") as f: return {x["record_id"]: x for x in csv.DictReader(f)}


def extension(content_type: str, url: str) -> str:
    c = content_type.lower().split(";", 1)[0]
    if c == "application/pdf": return ".pdf"
    if c in {"text/plain", "text/csv", "application/json", "application/xml", "text/xml"}: return ".txt"
    if c in {"text/html", "application/xhtml+xml"}: return ".html"
    ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return ext if ext in {".pdf", ".html", ".htm", ".txt"} else ".bin"


def safe_path(root: Path, record_id: str, suffix: str) -> Path:
    return root / record_id[:2] / f"{record_id}{suffix}"


def extract_pdf(path: Path) -> tuple[str, str]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return "", "pdf_extraction_unavailable_install_pypdf"
    try:
        pages = []
        for number, page in enumerate(PdfReader(str(path)).pages, 1):
            pages.append(f"[Page {number}]\n{page.extract_text() or ''}")
        text = "\n\n".join(pages).strip()
        return text, "success" if text else "empty_text"
    except Exception as exc:
        return "", f"failed: {exc}"


def extract_text(path: Path, content_type: str) -> tuple[str, str]:
    c = content_type.lower()
    if path.suffix == ".pdf" or "application/pdf" in c: return extract_pdf(path)
    try: raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc: return "", f"failed: {exc}"
    if "html" in c or path.suffix in {".html", ".htm"}:
        parser = TextExtractor(); parser.feed(raw); text = parser.text()
    else: text = raw.strip()
    return text, "success" if text else "empty_text"


def download(source: dict[str, str], document_dir: Path, text_dir: Path, max_bytes: int, user_agent: str, extract: bool = True) -> dict[str, Any]:
    rid, url = clean(source.get("record_id")), clean(source.get("url"))
    base = {"record_id": rid, "source_id": clean(source.get("source_id")), "source_name": clean(source.get("source_name")), "title": clean(source.get("title")), "original_url": url, "resolved_url": "", "local_document_path": "", "local_text_path": "", "content_type": "", "file_extension": "", "sha256": "", "bytes_downloaded": 0, "download_status": "", "extraction_status": "not_run", "http_status": "", "language": clean(source.get("language")), "evidence_class": clean(source.get("evidence_class")), "source_tier": clean(source.get("source_tier")), "rights_license": clean(source.get("rights_license")), "external_id": clean(source.get("external_id")), "retrieved_at": now(), "error": ""}
    if not rid or not url: base.update(download_status="invalid_record", error="record_id or URL is empty"); return base
    if urllib.parse.urlparse(url).scheme not in {"http", "https"}: base.update(download_status="unsupported_url", error="only http/https URLs are supported"); return base
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,*/*;q=0.1"})
        with urllib.request.urlopen(req, timeout=45) as response:
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            length = int(response.headers.get("Content-Length", "0") or 0)
            if length > max_bytes: raise RuntimeError(f"content length {length} exceeds max {max_bytes}")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes: raise RuntimeError(f"content exceeds max {max_bytes}")
            resolved = response.geturl(); status = response.status
        ext = extension(content_type, resolved); doc = safe_path(document_dir, rid, ext); doc.parent.mkdir(parents=True, exist_ok=True); doc.write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        text, extraction_status = extract_text(doc, content_type) if extract else ("", "not_requested")
        text_path = ""
        if text:
            txt = safe_path(text_dir, rid, ".txt"); txt.parent.mkdir(parents=True, exist_ok=True); txt.write_text(text, encoding="utf-8"); text_path = str(txt)
        base.update(resolved_url=resolved, local_document_path=str(doc), local_text_path=text_path, content_type=content_type, file_extension=ext, sha256=digest, bytes_downloaded=len(body), download_status="downloaded", extraction_status=extraction_status, http_status=status)
    except urllib.error.HTTPError as exc: base.update(download_status="http_error", http_status=exc.code, error=str(exc))
    except Exception as exc: base.update(download_status="download_error", error=str(exc))
    return base


def write_manifests(out_dir: Path, sources: list[dict[str, str]], results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = [results[clean(s.get("record_id"))] for s in sources if clean(s.get("record_id")) in results]
    (out_dir / "source_manifest.json").write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "source_manifest.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS); writer.writeheader(); writer.writerows(ordered)
    return ordered


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-file", type=Path, default=Path("cultural_crawl_4000/cultural_sources.csv"))
    ap.add_argument("--out-dir", type=Path, default=Path("cultural_crawl_4000/local_archive"))
    ap.add_argument("--limit", type=int, default=0, help="process only the first N records; 0 means all")
    ap.add_argument("--max-bytes", type=int, default=50_000_000)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--redownload", action="store_true")
    ap.add_argument("--no-text", action="store_true", help="save documents but skip text extraction")
    args = ap.parse_args(); args.out_dir.mkdir(parents=True, exist_ok=True); docs, texts = args.out_dir / "documents", args.out_dir / "extracted_text"; docs.mkdir(exist_ok=True); texts.mkdir(exist_ok=True)
    sources = [x for x in read_sources(args.source_file) if clean(x.get("language")).lower() == "en"]; sources = sources[:args.limit] if args.limit else sources
    manifest_path = args.out_dir / "source_manifest.json"; manifest = read_manifest(manifest_path); user_agent = os.environ.get("CRAWLER_USER_AGENT", "SETU-Culture-Downloader/1.0")
    results = dict(manifest); started = now()
    for i, source in enumerate(sources, 1):
        rid = clean(source.get("record_id"))
        if not args.redownload and rid in results and results[rid].get("download_status") == "downloaded": continue
        result = download(source, docs, texts, args.max_bytes, user_agent, extract=not args.no_text)
        results[rid] = result; ordered = write_manifests(args.out_dir, sources, results); time.sleep(max(0, args.sleep)); print(f"[{i}/{len(sources)}] {rid} {result['download_status']} {result['extraction_status']}")
    ordered = write_manifests(args.out_dir, sources, results)
    from collections import Counter
    report={"started_at":started,"finished_at":now(),"source_file":str(args.source_file),"records_selected":len(sources),"manifest_records":len(ordered),"status_counts":dict(Counter(x.get("download_status") for x in ordered)),"extraction_counts":dict(Counter(x.get("extraction_status") for x in ordered)),"max_bytes":args.max_bytes,"text_extraction_requested":not args.no_text,"request_delay_seconds":args.sleep}
    (args.out_dir / "download_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Completed {len(ordered)} records. Manifest: {manifest_path}")

if __name__ == "__main__": main()
