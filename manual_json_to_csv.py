#!/usr/bin/env python3
"""Convert paired manual extraction/generation JSON files to the SETU CSV schema."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

import setu_benchmark_pipeline as pipeline


ROOT = Path(__file__).resolve().parent
DEFAULT_MANUAL_DIR = ROOT / "Manual"


def read_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"{path} is empty; write valid JSON before running the converter")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} contains invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def paired_files(manual_dir: Path) -> list[tuple[Path, Path]]:
    extraction_dir = manual_dir / "Extraction"
    generation_dir = manual_dir / "Generation"
    extraction_files = {path.stem: path for path in extraction_dir.glob("*.json")}
    generation_files = {path.stem: path for path in generation_dir.glob("*.json")}
    missing_generation = sorted(extraction_files.keys() - generation_files.keys())
    missing_extraction = sorted(generation_files.keys() - extraction_files.keys())
    if missing_generation or missing_extraction:
        raise ValueError(
            f"unpaired files; missing generation={missing_generation}, "
            f"missing extraction={missing_extraction}"
        )
    return [(extraction_files[stem], generation_files[stem]) for stem in sorted(extraction_files)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual-dir", type=Path, default=DEFAULT_MANUAL_DIR)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--author", default=os.environ.get("SETU_AUTHOR", ""))
    parser.add_argument("--llm-used", default=os.environ.get("LLM_MODEL", pipeline.MODEL))
    args = parser.parse_args()

    output = args.output or args.manual_dir / "setu_culture_questions.csv"
    output_fields = [field for field in pipeline.FINAL_FIELDS if field != "Instance_ID"]

    old_author, old_model = pipeline.AUTHOR, pipeline.MODEL
    pipeline.AUTHOR, pipeline.MODEL = args.author, args.llm_used
    rows: list[dict[str, Any]] = []
    dropped_low_confidence = 0
    try:
        pairs = paired_files(args.manual_dir)
        for extraction_path, generation_path in pairs:
            extraction = read_json(extraction_path)
            if not isinstance(extraction, dict):
                raise ValueError(f"{extraction_path} must contain one JSON object")
            if str(extraction.get("confidence", "")).strip().lower() == "low":
                dropped_low_confidence += 1
                continue

            packages = read_json(generation_path)
            if not isinstance(packages, list) or not packages:
                raise ValueError(f"{generation_path} must contain a non-empty JSON array")

            source_link = str(extraction.get("source_link", "")).strip()
            if not source_link:
                raise ValueError(f"{extraction_path} is missing source_link")
            item = {
                "Instance_ID": extraction_path.stem,
                "resolved_url": source_link,
                "source_id": "manual",
                "source_type": "manual",
                "source_name": "Manual source",
                "evidence_class": "manual_review",
            }
            extraction_for_output = dict(extraction)
            categories = extraction.get("shared_elements_categories", [])
            if isinstance(categories, (list, tuple)):
                extraction_for_output["shared_elements"] = "; ".join(
                    str(category).strip() for category in categories if str(category).strip()
                )
            elif categories:
                extraction_for_output["shared_elements"] = str(categories).strip()

            for question_number, package in enumerate(packages, 1):
                if not isinstance(package, dict):
                    raise ValueError(f"{generation_path} package {question_number} is not an object")
                randomized = pipeline.randomize_mcq_options(package)
                row = pipeline.flatten(item, extraction_for_output, randomized, question_number)
                row["Trustworthy_Class"] = 1
                row.pop("Instance_ID", None)
                rows.append(row)
    finally:
        pipeline.AUTHOR, pipeline.MODEL = old_author, old_model

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"Converted {len(pairs)} paired samples; dropped {dropped_low_confidence} "
        f"low-confidence sources; wrote {len(rows)} rows to {output}"
    )


if __name__ == "__main__":
    main()
