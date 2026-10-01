#!/usr/bin/env python3
"""Generate SETU-Culture questions from YouTube transcripts."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore

import setu_benchmark_pipeline as base


ROOT = Path(__file__).resolve().parent
DEFAULT_TRANSCRIPTS = ROOT / "cultural_crawl_youtube" / "transcripts" / "transcripts.jsonl"
DEFAULT_OUTPUT = ROOT / "setu_youtube_generated"
AUTHOR = os.environ.get("SETU_AUTHOR", "")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://agentrouter.org/v1")
API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "gpt-5.6-sol")
USER_AGENT = os.environ.get("LLM_USER_AGENT", "Kilo-Code/5.3.0")
STAINLESS_LANG = os.environ.get("LLM_STAINLESS_LANG", "python")
MAX_RETRIES = 4


EXTRACTION_PROMPT = """You are Prompt 1 for SETU-Culture, analyzing one YouTube transcript as popular-secondary cultural evidence. Use only the supplied video metadata and transcript. Do not use outside knowledge and do not infer that similarity proves borrowing. YouTube content may be inaccurate, incomplete, promotional, hateful, graphic, or sensitive. Ignore sensitive content entirely: do not quote, summarize, classify, reproduce, or use it as evidence. If the omitted or unreliable content is necessary, write unknown/uncertain.

Assign one or more relationship labels from this taxonomy only when supported: {taxonomy}
Assign one or more shared-elements categories only when clearly supported: {categories}

Return ONLY JSON with exactly these keys:
{{
  "source_language": "",
  "relationship_label_suggested": ["A_documented_transmission"],
  "culture_a_period": "",
  "culture_b_period": "",
  "shared_elements": "",
  "extraction_summary": "",
  "transmission_evidence_summary": "",
  "local_transformation_summary": "",
  "uncertainty_notes": "",
  "confidence": "high|medium|low"
}}

VIDEO METADATA:
{source}
TRANSCRIPT:
{transcript}
"""

GENERATION_PROMPT = """You are Prompt 2 for SETU-Culture. Generate EXACTLY THREE DISTINCT benchmark question packages from only the supplied YouTube metadata, transcript, and Prompt 1 extraction. Treat the transcript as popular-secondary evidence: preserve attribution and uncertainty, never turn an unsupported video claim into fact, and use unknown/uncertain when evidence is insufficient.

Ignore sensitive content entirely. Do not quote, elaborate on, or reproduce graphic, hateful, explicit, or personally identifying material. If such material is necessary to answer a question, make the question unknown/uncertain instead.

Return ONLY a JSON array of exactly three objects with exactly these keys:
[
{{
  "culture_a_country_region": "", "culture_b_country_region": "",
  "scenario": "2-4 neutral sentences grounded in the transcript and extraction",
  "mcq_question": "", "option_a": "", "option_b": "", "option_c": "", "option_d": "",
  "option_a_distractor_type": "correct|overclaim|underclaim|wrong_direction|other",
  "option_b_distractor_type": "correct|overclaim|underclaim|wrong_direction|other",
  "option_c_distractor_type": "correct|overclaim|underclaim|wrong_direction|other",
  "option_d_distractor_type": "correct|overclaim|underclaim|wrong_direction|other",
  "mcq_expected_reasoning": "",
  "true_false_statement_question": "",
  "true_false_statement_type": "correct_relationship|overclaim|underclaim|wrong_direction",
  "statement_is_true": true,
  "required_justification": "",
  "true_false_expected_reasoning": "",
  "explanation_question": "", "required_answer": "", "explanation_expected_reasoning": ""
}},
{{ ...same keys, distinct package... }},
{{ ...same keys, distinct package... }}
]

Use either exactly two false and one true, or exactly one false and two true, across the three `statement_is_true` values. Never use three true or three false. Vary the correct MCQ option position and keep each option paired with its distractor type. The explanation must identify the relationship and distinguish evidence from unsupported claims.

VIDEO METADATA:
{source}
PROMPT 1 EXTRACTION:
{extraction}
TRANSCRIPT:
{transcript}
"""


def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return data


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def call_llm(prompt: str) -> Any:
    if OpenAI is None:
        raise RuntimeError("install the openai package before an LLM stage")
    if not API_KEY:
        raise RuntimeError("Set LLM_API_KEY before an LLM stage")
    client = OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
        default_headers={"User-Agent": USER_AGENT, "x-stainless-lang": STAINLESS_LANG},
    )
    last: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL, max_tokens=4500, temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            return base.clean_json(response.choices[0].message.content or "")
        except Exception as exc:
            last = exc
            if attempt < MAX_RETRIES:
                time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} attempts: {last}")


def truth_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if value == "true": return True
        if value == "false": return False
    return None


def transcript_index(path: Path) -> dict[str, dict[str, Any]]:
    return {str(row.get("record_id")): row for row in read_rows(path) if row.get("record_id")}


def process_batch(batch_file: Path, transcript_file: Path, out_dir: Path, stage: str, dry_run: bool, max_text_chars: int) -> None:
    items = read_rows(batch_file)
    transcripts = transcript_index(transcript_file)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompts").mkdir(exist_ok=True)
    write_json(out_dir / "prompts" / "prompt_1_extraction.json", {"template": EXTRACTION_PROMPT, "taxonomy": base.TAXONOMY, "categories": base.SHARED_CATEGORIES})
    write_json(out_dir / "prompts" / "prompt_2_generation.json", {"template": GENERATION_PROMPT})
    extraction_path = out_dir / "01_extractions.jsonl"
    generation_path = out_dir / "02_generations.jsonl"
    extracted = {row["Instance_ID"]: row for row in read_rows(extraction_path)} if extraction_path.exists() else {}
    generated = {row["Instance_ID"]: row for row in read_rows(generation_path)} if generation_path.exists() else {}
    errors: list[dict[str, str]] = []
    dropped_low = set()

    for item in items:
        iid = str(item.get("Instance_ID") or item.get("record_id"))
        item["Instance_ID"] = iid
        transcript_row = transcripts.get(str(item.get("record_id")))
        if not transcript_row or transcript_row.get("download_status") != "downloaded" or not transcript_row.get("transcript"):
            errors.append({"stage": "transcript", "instance_id": iid, "error": "downloaded transcript is missing"})
            continue
        transcript = str(transcript_row["transcript"])[:max_text_chars]
        source = dict(item)
        source["resolved_url"] = item.get("url", "")
        source["transcript_language"] = transcript_row.get("transcript_language", "")
        source["transcript_type"] = transcript_row.get("transcript_type", "")

        if stage in ("extract", "all") and iid not in extracted:
            prompt = EXTRACTION_PROMPT.format(
                taxonomy=json.dumps(base.TAXONOMY, ensure_ascii=False),
                categories=", ".join(base.SHARED_CATEGORIES), source=json.dumps(source, ensure_ascii=False), transcript=transcript,
            )
            try:
                result = {"Instance_ID": iid, "source": source, "prompt": prompt, "extraction": {} if dry_run else call_llm(prompt)}
                with extraction_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                extracted[iid] = result
            except Exception as exc:
                errors.append({"stage": "extract", "instance_id": iid, "error": str(exc)})

        extraction = extracted.get(iid, {}).get("extraction", {})
        if isinstance(extraction, dict) and str(extraction.get("confidence", "")).strip().lower() == "low":
            dropped_low.add(iid)
            errors.append({"stage": "confidence_filter", "instance_id": iid, "error": "Prompt 1 confidence is low; Prompt 2 was not executed"})
            continue

        if stage in ("generate", "all") and not dry_run and iid in extracted and iid not in generated:
            prompt = GENERATION_PROMPT.format(source=json.dumps(source, ensure_ascii=False), extraction=json.dumps(extraction, ensure_ascii=False), transcript=transcript)
            try:
                result = {"Instance_ID": iid, "prompt": prompt, "generation": call_llm(prompt)}
                with generation_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                generated[iid] = result
            except Exception as exc:
                errors.append({"stage": "generate", "instance_id": iid, "error": str(exc)})

    final: list[dict[str, Any]] = []
    for item in items:
        iid = str(item.get("Instance_ID") or item.get("record_id"))
        if iid in dropped_low or iid not in extracted or iid not in generated:
            continue
        packages = generated[iid].get("generation", [])
        if isinstance(packages, dict): packages = [packages]
        if len(packages) != 3:
            errors.append({"stage": "generate_validation", "instance_id": iid, "error": f"expected 3 packages, received {len(packages)}"})
            continue
        values = [truth_value(package.get("statement_is_true")) for package in packages if isinstance(package, dict)]
        if len(values) != 3 or any(value is None for value in values) or sum(value is True for value in values) not in (1, 2):
            errors.append({"stage": "generate_validation", "instance_id": iid, "error": "true/false values are not balanced 1/2 or 2/1"})
            continue
        for number, package in enumerate(packages, 1):
            final.append(base.flatten(item, extracted[iid].get("extraction", {}), base.randomize_mcq_options(package), number))

    write_json(out_dir / "setu_culture_questions.json", final)
    with (out_dir / "setu_culture_questions.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=base.FINAL_FIELDS)
        writer.writeheader()
        writer.writerows(final)
    if errors:
        (out_dir / "errors.log").write_text("\n".join(json.dumps(error, ensure_ascii=False) for error in errors) + "\n", encoding="utf-8")
    print(f"Processed {len(items)} sources; dropped {len(dropped_low)} low-confidence sources; generated {len(final)} complete items. Output: {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-file", type=Path, required=True)
    parser.add_argument("--transcript-file", type=Path, default=DEFAULT_TRANSCRIPTS)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=("extract", "generate", "all"), default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-text-chars", type=int, default=120000)
    args = parser.parse_args()
    process_batch(args.batch_file, args.transcript_file, args.out_dir, args.stage, args.dry_run, args.max_text_chars)


if __name__ == "__main__":
    main()
