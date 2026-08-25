#!/usr/bin/env python3
"""Generate SETU-Culture benchmark items from crawled source pairs.

The pipeline is deliberately file-backed and resumable:

  1. ``extract`` resolves both source URLs in the benchmark template against
     ``all_records.csv`` and asks Prompt 1 for evidence-grounded fields.
  2. ``generate`` asks Prompt 2 for a scenario, MCQ, true/false item, and
     explanation question using only the extraction JSON.
  3. ``all`` runs both stages and writes flattened JSON and CSV deliverables.

The default output directory is ``Project/setu_culture_generated``.  API
access uses any OpenAI-compatible endpoint via LLM_API_KEY, LLM_BASE_URL and
LLM_MODEL, matching Project/main.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import csv as _csv
from pathlib import Path
from typing import Any, Dict, Iterable, List

_csv.field_size_limit(max(_csv.field_size_limit(), 10 * 1024 * 1024))

try:
    from openai import OpenAI
except ImportError:  # extraction-only and --dry-run remain usable
    OpenAI = None  # type: ignore


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT.parent / "setu_culture_outputs"
DEFAULT_OUTPUT = ROOT / "setu_culture_generated"
AUTHOR = os.environ.get("SETU_AUTHOR", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://agentrouter.org/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "gpt-5.6-sol")
MAX_RETRIES = 4

RELATIONSHIP_TAXONOMY = {
    "A_documented_transmission": "demonstrable movement through trade, pilgrimage, translation, migration, conquest, diplomacy, or missionary activity",
    "B_localization_adaptation": "a transmitted element retained but renamed, reinterpreted, visually transformed, or embedded in local practice",
    "C_syncretism_religious_integration": "elements from multiple traditions combine into a new local religious or cultural form",
    "D_parallel_motif_convergent_similarity": "a shared structural idea without sufficient evidence that one tradition came from the other",
    "E_contested_or_uncertain_relationship": "a proposed link whose evidence is incomplete, disputed, or chronologically unclear",
    "F_false_friend_superficial_resemblance": "items look similar but are unrelated in meaning, function, chronology, or origin",
}

EXTRACTION_PROMPT = """You are Prompt 1 of the SETU-Culture benchmark. Extract only information supported by the two source records below. Do not use outside knowledge and do not turn lexical or visual resemblance into ancestry.

Assign exactly one relationship label from this taxonomy:
{taxonomy}

For each culture, give the earliest verified date or period range supported by its source; explicitly say unknown/uncertain where needed. Identify exactly one shared element category from: religion_and_philosophy, epics_and_narrative_traditions, deities_symbols_and_iconography, architecture_and_sacred_landscapes, festivals_and_ritual_calendars, food_and_ritual_offerings, performing_arts, kinship_kingship_and_political_symbolism, mythic_motifs, cultural_misconception_correction. The label must be cautious: resemblance alone supports parallel, uncertain, or false-friend, never transmission/localization/syncretism.

Return ONLY JSON:
{{
  "relationship_label_suggested": "A_documented_transmission|B_localization_adaptation|C_syncretism_religious_integration|D_parallel_motif_convergent_similarity|E_contested_or_uncertain_relationship|F_false_friend_superficial_resemblance",
  "culture_a_period": "",
  "culture_b_period": "",
  "shared_elements": "",
  "transmission_evidence_summary": "",
  "local_transformation_summary": "",
  "extraction_summary": "",
  "uncertainty_notes": "",
  "confidence": "high|medium|low"
}}

CULTURE A METADATA:
{a_meta}
CULTURE A SOURCE TEXT:
{a_text}

CULTURE B METADATA:
{b_meta}
CULTURE B SOURCE TEXT:
{b_text}
"""

GENERATION_PROMPT = """You are Prompt 2 of the SETU-Culture benchmark. Generate questions from ONLY the metadata and extraction below. Preserve uncertainty and never claim that similarity proves borrowing. The scenario must not state the answer directly.

Return ONLY JSON with exactly these keys:
{{
  "scenario": "2-4 neutral sentences",
  "mcq_question": "",
  "option_a": "", "option_b": "", "option_c": "", "option_d": "",
  "option_a_distractor_type": "correct|overclaim|underclaim|wrong_direction|other",
  "option_b_distractor_type": "correct|overclaim|underclaim|wrong_direction|other",
  "option_c_distractor_type": "correct|overclaim|underclaim|wrong_direction|other",
  "option_d_distractor_type": "correct|overclaim|underclaim|wrong_direction|other",
  "mcq_correct_option": "A|B|C|D",
  "mcq_expected_reasoning": "",
  "true_false_statement_question": "",
  "true_false_statement_type": "correct_relationship|overclaim|underclaim|wrong_direction",
  "statement_is_true": true,
  "required_justification": "",
  "true_false_expected_reasoning": "",
  "explanation_question": "",
  "required_answer": "",
  "explanation_expected_reasoning": ""
}}

The MCQ must have one unambiguous answer, at least one overclaim distractor and one underclaim or wrong-direction distractor. The true/false item must test a different claim from the MCQ. The explanation must require naming the relationship and explaining continuity/change or, for uncertain/parallel/false-friend cases, what evidence is missing and why resemblance is insufficient.

TEMPLATE METADATA:
{metadata}
EXTRACTION JSON:
{extraction}
"""

FINAL_FIELDS = [
    "Author", "LLM_Used", "Instance_ID", "Culture_A_Source", "Culture_A_Source_Language",
    "Culture_A_Country", "Culture_A_Region", "Culture_A_Macro_Region", "Culture_A_Evidence_Class",
    "Culture_B_Source", "Culture_B_Source_Language", "Culture_B_Country", "Culture_B_Region",
    "Culture_B_Macro_Region", "Culture_B_Evidence_Class", "Supporting_Evidences",
    "Contradictory/Refuting_Evidence", "Relationship_Label_Suggested", "Relationship_Label_Confirmed",
    "Culture_A_Period", "Culture_B_Period", "Shared_Elements", "Scenario", "MCQ_Question",
    "Option_A", "Option_B", "Option_C", "Option_D", "Option_A_Distractor_Type",
    "Option_B_Distractor_Type", "Option_C_Distractor_Type", "Option_D_Distractor_Type",
    "MCQ_Correct_Option", "MCQ_Expected_Reasoning", "True/False_Statement_Question",
    "True/False_Statement_Type", "Statement_Is_True", "Required_Justification",
    "True/False_Expected_Reasoning", "Explanation_Question", "Required_Answer",
    "Explanation_Expected_Reasoning",
]


def read_csv(path: Path) -> Iterable[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_instance_json(directory: Path, instance_id: str, row: Dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", instance_id)
    (directory / f"{safe_id}.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")


def log_error(out_dir: Path, stage: str, instance_id: str, exc: Exception) -> None:
    with (out_dir / "errors.log").open("a", encoding="utf-8") as f:
        f.write(f"[{stage}] instance_id={instance_id} error={exc}\n")
    print(f"[{stage}] failed for {instance_id}: {exc}", file=sys.stderr)


def clean_json(text: str) -> Dict[str, Any]:
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.I)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def call_llm(prompt: str) -> Dict[str, Any]:
    if OpenAI is None:
        raise RuntimeError("openai package is required for LLM stages; use --dry-run for local preparation")
    if not LLM_API_KEY:
        raise RuntimeError("Set LLM_API_KEY (and optionally LLM_BASE_URL/LLM_MODEL) before an LLM stage")
    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL, max_tokens=4500, temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            return clean_json(response.choices[0].message.content or "")
        except Exception as exc:  # retry transient provider/JSON failures
            last = exc
            if attempt < MAX_RETRIES:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} attempts: {last}")


def source_index(records_path: Path) -> Dict[str, Dict[str, str]]:
    index: Dict[str, Dict[str, str]] = {}
    for row in read_csv(records_path):
        url = (row.get("url") or "").strip()
        if url and url not in index:
            index[url] = row
    return index


def source_payload(url: str, row: Dict[str, str] | None) -> Dict[str, Any]:
    row = row or {}
    text = (row.get("description") or "").strip()
    if not text:
        text = "No crawled description is available; use metadata only and mark uncertainty."
    return {
        "url": url, "title": row.get("title", ""), "language": row.get("language", ""),
        "country": row.get("country", ""), "region": row.get("region", ""),
        "macro_region": row.get("macro_region", ""), "evidence_class": row.get("evidence_class", ""),
        "source_tier": row.get("source_tier", ""), "text": text[:30000],
    }


def metadata(row: Dict[str, str], a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    return {"instance_id": row.get("instance_id", ""), "author": AUTHOR, "llm_used": MODEL,
            "culture_a": {"country": row.get("culture_a_country", ""), "region": row.get("culture_a_region", ""),
                          "source_language": row.get("culture_a_source_language", "") or a.get("language", ""),
                          "evidence_class": row.get("culture_a_evidence_class", "")},
            "culture_b": {"country": row.get("culture_b_country", ""), "region": row.get("culture_b_region", ""),
                          "source_language": row.get("culture_b_source_language", "") or b.get("language", ""),
                          "evidence_class": row.get("culture_b_evidence_class", "")},
            "culture_a_source": row.get("culture_a_source", ""), "culture_b_source": row.get("culture_b_source", ""),
            "a_macro_region": a.get("macro_region", ""), "b_macro_region": b.get("macro_region", ""),
            "template_shared_element": row.get("shared_element", ""), "template_provenance": row.get("provenance_note", "")}


def build_extraction(row: Dict[str, str], a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    prompt = EXTRACTION_PROMPT.format(
        taxonomy=json.dumps(RELATIONSHIP_TAXONOMY, ensure_ascii=False),
        a_meta=json.dumps(a, ensure_ascii=False), b_meta=json.dumps(b, ensure_ascii=False),
        a_text=a["text"], b_text=b["text"])
    return {"instance_id": row["instance_id"], "prompt": prompt, "extraction": call_llm(prompt)}


def flatten(row: Dict[str, str], a: Dict[str, Any], b: Dict[str, Any], extraction: Dict[str, Any], generation: Dict[str, Any]) -> Dict[str, Any]:
    def g(key: str, default: Any = "") -> Any: return generation.get(key, default)
    return {
        "Author": AUTHOR, "LLM_Used": MODEL, "Instance_ID": row.get("instance_id", ""),
        "Culture_A_Source": row.get("culture_a_source", ""), "Culture_A_Source_Language": row.get("culture_a_source_language", "") or a.get("language", ""),
        "Culture_A_Country": row.get("culture_a_country", ""), "Culture_A_Region": row.get("culture_a_region", ""),
        "Culture_A_Macro_Region": a.get("macro_region", ""), "Culture_A_Evidence_Class": row.get("culture_a_evidence_class", ""),
        "Culture_B_Source": row.get("culture_b_source", ""), "Culture_B_Source_Language": row.get("culture_b_source_language", "") or b.get("language", ""),
        "Culture_B_Country": row.get("culture_b_country", ""), "Culture_B_Region": row.get("culture_b_region", ""),
        "Culture_B_Macro_Region": b.get("macro_region", ""), "Culture_B_Evidence_Class": row.get("culture_b_evidence_class", ""),
        "Supporting_Evidences": "", "Contradictory/Refuting_Evidence": "",
        "Relationship_Label_Suggested": extraction.get("relationship_label_suggested", ""), "Relationship_Label_Confirmed": "",
        "Culture_A_Period": extraction.get("culture_a_period", ""), "Culture_B_Period": extraction.get("culture_b_period", ""),
        "Shared_Elements": extraction.get("shared_elements", ""), "Scenario": g("scenario"),
        "MCQ_Question": g("mcq_question"), "Option_A": g("option_a"), "Option_B": g("option_b"), "Option_C": g("option_c"), "Option_D": g("option_d"),
        "Option_A_Distractor_Type": g("option_a_distractor_type"), "Option_B_Distractor_Type": g("option_b_distractor_type"),
        "Option_C_Distractor_Type": g("option_c_distractor_type"), "Option_D_Distractor_Type": g("option_d_distractor_type"),
        "MCQ_Correct_Option": g("mcq_correct_option"), "MCQ_Expected_Reasoning": g("mcq_expected_reasoning"),
        "True/False_Statement_Question": g("true_false_statement_question"), "True/False_Statement_Type": g("true_false_statement_type"),
        "Statement_Is_True": g("statement_is_true"), "Required_Justification": g("required_justification"),
        "True/False_Expected_Reasoning": g("true_false_expected_reasoning"), "Explanation_Question": g("explanation_question"),
        "Required_Answer": g("required_answer"), "Explanation_Expected_Reasoning": g("explanation_expected_reasoning"),
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FINAL_FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--stage", choices=("extract", "generate", "all"), default="all")
    ap.add_argument("--limit", type=int, default=0, help="process only the first N template rows")
    ap.add_argument("--dry-run", action="store_true", help="prepare source-pair JSONL without calling the LLM")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "prompts").mkdir(exist_ok=True)
    (args.out_dir / "prompts" / "prompt_1_extraction.txt").write_text(EXTRACTION_PROMPT, encoding="utf-8")
    (args.out_dir / "prompts" / "prompt_2_generation.txt").write_text(GENERATION_PROMPT, encoding="utf-8")
    extraction_dir = args.out_dir / "01_extractions"
    generation_dir = args.out_dir / "02_generations"
    final_dir = args.out_dir / "final"
    extraction_dir.mkdir(exist_ok=True)
    generation_dir.mkdir(exist_ok=True)
    final_dir.mkdir(exist_ok=True)
    rows = list(read_csv(args.input_dir / "benchmark_instance_template.csv"))
    if args.limit: rows = rows[:args.limit]
    idx = source_index(args.input_dir / "all_records.csv")
    pairs = []
    for row in rows:
        a = source_payload(row.get("culture_a_source", ""), idx.get(row.get("culture_a_source", "")))
        b = source_payload(row.get("culture_b_source", ""), idx.get(row.get("culture_b_source", "")))
        pairs.append((row, a, b))
    extraction_path = args.out_dir / "01_extractions.jsonl"
    generation_path = args.out_dir / "02_generations.jsonl"
    if args.stage in ("extract", "all"):
        done = {x.get("instance_id") for x in read_jsonl(extraction_path)}
        for row, a, b in pairs:
            if row["instance_id"] in done: continue
            payload = {"instance_id": row["instance_id"], "metadata": metadata(row, a, b), "source_a": a, "source_b": b}
            try:
                if args.dry_run:
                    payload["prompt"] = EXTRACTION_PROMPT.format(taxonomy=json.dumps(RELATIONSHIP_TAXONOMY), a_meta=json.dumps(a), b_meta=json.dumps(b), a_text=a["text"], b_text=b["text"])
                else:
                    payload.update(build_extraction(row, a, b))
                append_jsonl(extraction_path, payload)
                write_instance_json(extraction_dir, row["instance_id"], payload)
            except Exception as exc:
                log_error(args.out_dir, "extract", row["instance_id"], exc)
    if args.stage in ("generate", "all") and not args.dry_run:
        extracted = {x["instance_id"]: x for x in read_jsonl(extraction_path)}
        done = {x.get("instance_id") for x in read_jsonl(generation_path)}
        for row, a, b in pairs:
            if row["instance_id"] in done or row["instance_id"] not in extracted: continue
            inst = extracted[row["instance_id"]]
            prompt = GENERATION_PROMPT.format(metadata=json.dumps(inst["metadata"], ensure_ascii=False), extraction=json.dumps(inst.get("extraction", {}), ensure_ascii=False))
            try:
                result = {"instance_id": row["instance_id"], "prompt": prompt, "generation": call_llm(prompt)}
                append_jsonl(generation_path, result)
                write_instance_json(generation_dir, row["instance_id"], result)
            except Exception as exc:
                log_error(args.out_dir, "generate", row["instance_id"], exc)
    if args.stage in ("generate", "all") and not args.dry_run:
        extracted = {x["instance_id"]: x for x in read_jsonl(extraction_path)}
        generated = {x["instance_id"]: x.get("generation", {}) for x in read_jsonl(generation_path)}
        final = []
        for row, a, b in pairs:
            if row["instance_id"] in generated and row["instance_id"] in extracted:
                final.append(flatten(row, a, b, extracted[row["instance_id"]].get("extraction", {}), generated[row["instance_id"]]))
        (final_dir / "setu_culture_questions.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
        write_csv(final_dir / "setu_culture_questions.csv", final)
    print(f"Processed {len(pairs)} template rows. Output: {args.out_dir}")


if __name__ == "__main__":
    main()
