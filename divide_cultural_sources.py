#!/usr/bin/env python3
"""Divide cultural_sources.csv into three equal validator groups, one English-only."""
from __future__ import annotations

import argparse, csv, sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_FILE = ROOT / "cultural_crawl_4000" / "cultural_sources.csv"
DEFAULT_OUT_DIR = ROOT / "cultural_crawl_4000" / "Division"

ENGLISH_GROUP = "Suruchi_english_only_sources.csv"
OTHER_GROUPS = ["Ankit_culture_sources.csv", "Avhinash_culture_sources.csv"]


def is_english(row: dict[str, Any]) -> bool:
    return (row.get("language") or "").strip().lower() == "en"


def stratum(row: dict[str, Any]) -> str:
    return (row.get("query_group") or "").strip()


def allocate(sizes: dict[str, int], total: int) -> dict[str, int]:
    """Split `total` across strata proportionally, largest-remainder for the rest."""
    pool = sum(sizes.values())
    if total > pool: raise ValueError(f"cannot take {total} rows from a pool of {pool}")
    exact = {k: v * total / pool for k, v in sizes.items()}
    take = {k: min(int(v), sizes[k]) for k, v in exact.items()}
    order = sorted(sizes, key=lambda k: (-(exact[k] - int(exact[k])), k))
    while sum(take.values()) < total:
        for k in order:
            if sum(take.values()) == total: break
            if take[k] < sizes[k]: take[k] += 1
    return take


def spread(rows: list[dict[str, Any]], k: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pick k rows spaced evenly across `rows`; return (picked, leftover)."""
    n = len(rows)
    if k >= n: return list(rows), []
    picked = {round(i * n / k) for i in range(k)}
    while len(picked) < k:
        picked.update(i for i in range(n) if i not in picked and len(picked) < k)
    return [rows[i] for i in sorted(picked)], [rows[i] for i in range(n) if i not in picked]


def divide(source_file: Path, out_dir: Path) -> None:
    with source_file.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields, rows = list(reader.fieldnames or []), list(reader)
    total = len(rows)
    if total % 3: print(f"note: {total} rows is not divisible by 3; sizes differ by 1", file=sys.stderr)
    target = [total // 3 + (1 if i < total % 3 else 0) for i in range(3)]

    english = [r for r in rows if is_english(r)]
    if len(english) < target[0]:
        raise SystemExit(f"only {len(english)} English rows; need {target[0]} for the English-only group")

    # Group 1: English only, sampled proportionally across query_group.
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for row in english: by_stratum.setdefault(stratum(row), []).append(row)
    quota = allocate({k: len(v) for k, v in by_stratum.items()}, target[0])
    group_one, leftover = [], []
    for key in sorted(by_stratum):
        picked, rest = spread(by_stratum[key], quota[key])
        group_one += picked; leftover += rest

    # Groups 2 and 3: everything else, stratified by query_group and language, dealt alternately.
    chosen = {id(r) for r in group_one}
    remaining: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    for row in rows:
        if id(row) in chosen: continue
        remaining.setdefault((stratum(row), is_english(row)), []).append(row)
    ordered = [r for key in sorted(remaining) for r in remaining[key]]
    group_two = [r for i, r in enumerate(ordered) if i % 2 == 0]
    group_three = [r for i, r in enumerate(ordered) if i % 2 == 1]
    while len(group_two) > target[1]: group_three.append(group_two.pop())
    while len(group_three) > target[2]: group_two.append(group_three.pop())

    # Mixed groups list their English rows first; the stratified order is kept within each half.
    group_two = sorted(group_two, key=lambda r: not is_english(r))
    group_three = sorted(group_three, key=lambda r: not is_english(r))

    groups = [(ENGLISH_GROUP, group_one), (OTHER_GROUPS[0], group_two), (OTHER_GROUPS[1], group_three)]
    seen, out_dir = set(), out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, group in groups:
        ids = {r["record_id"] for r in group}
        if ids & seen: raise SystemExit(f"{name} overlaps an earlier group")
        seen |= ids
        with (out_dir / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader(); w.writerows(group)
        non_english = sum(1 for r in group if not is_english(r))
        print(f"{name}: {len(group)} rows, {len(group) - non_english} English, {non_english} other")
    if len(seen) != total: raise SystemExit(f"partition covers {len(seen)} of {total} record_ids")
    print(f"Partitioned all {total} rows into {len(groups)} groups. Output: {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-file", type=Path, default=DEFAULT_SOURCE_FILE)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args()
    divide(args.source_file, args.out_dir)


if __name__ == "__main__": main()
