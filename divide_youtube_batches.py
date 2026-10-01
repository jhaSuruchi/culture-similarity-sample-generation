#!/usr/bin/env python3
"""Divide YouTube source records into fixed-size JSON and CSV batches."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "cultural_crawl_youtube" / "cultural_sources.json"
DEFAULT_OUT_DIR = ROOT / "cultural_crawl_youtube" / "batches_100"


def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")

    rows = read_rows(args.source_file)
    if not rows:
        parser.error("source file contains no records")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for offset in range(0, len(rows), args.batch_size):
        batch_number = offset // args.batch_size + 1
        batch = rows[offset:offset + args.batch_size]
        stem = f"batch_{batch_number:04d}"
        (args.out_dir / f"{stem}.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        fields = list(batch[0].keys())
        with (args.out_dir / f"{stem}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(batch)
    batches = (len(rows) + args.batch_size - 1) // args.batch_size
    print(f"Wrote {batches} batches for {len(rows)} records to {args.out_dir}")
    print(f"Batch sizes: {args.batch_size} full records; final batch has {len(rows) % args.batch_size or args.batch_size}")


if __name__ == "__main__":
    main()
