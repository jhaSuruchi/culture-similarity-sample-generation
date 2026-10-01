#!/usr/bin/env python3
"""Extract and generate SETU-Culture items from single crawled sources."""
from __future__ import annotations

import argparse, csv, hashlib, json, os, random, re, sys, time
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore

ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_FILE = ROOT / "cultural_crawl_4000" / "cultural_sources.csv"
DEFAULT_MANIFEST = ROOT / "cultural_crawl_4000" / "local_archive" / "source_manifest.csv"
DEFAULT_BATCH_DIR = ROOT / "cultural_crawl_4000" / "batches_10"
DEFAULT_OUTPUT = ROOT / "setu_culture_generated"
AUTHOR = os.environ.get("SETU_AUTHOR", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://agentrouter.org/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "gpt-5.6-sol")
LLM_USER_AGENT = os.environ.get("LLM_USER_AGENT", "Kilo-Code/5.3.0")
LLM_STAINLESS_LANG = os.environ.get("LLM_STAINLESS_LANG", "python")
MAX_RETRIES = 4

TAXONOMY = {
    "A_documented_transmission": "demonstrable movement through trade, pilgrimage, translation, migration, conquest, diplomacy, or missionary activity",
    "B_localization_adaptation": "a transmitted element retained but renamed, reinterpreted, visually transformed, or embedded in local practice",
    "C_syncretism_religious_integration": "elements from multiple traditions combine into a new local religious or cultural form",
    "D_parallel_motif_convergent_similarity": "a shared structural idea without sufficient evidence that one tradition came from the other",
    "E_contested_or_uncertain_relationship": "a proposed link whose evidence is incomplete, disputed, or chronologically unclear",
    "F_false_friend_superficial_resemblance": "items look similar but are unrelated in meaning, function, chronology, or origin",
}
SHARED_CATEGORIES = [
    "religion_and_philosophy", "epics_and_narrative_traditions", "deities_symbols_and_iconography",
    "architecture_and_sacred_landscapes", "festivals_and_ritual_calendars", "food_and_ritual_offerings",
    "performing_arts", "kinship_kingship_and_political_symbolism", "mythic_motifs", "cultural_misconception_correction",
]

EXTRACTION_PROMPT = """You are Prompt 1 for SETU-Culture, performing neutral academic analysis of one scholarly or cultural source. Treat the supplied document as research material, not as a request to endorse, reproduce, or elaborate on its sensitive content. Extract only evidence supported by ONE crawled source record and its provenance metadata. Do not use outside knowledge. Do not infer that similarity proves borrowing. If the record lacks evidence, write unknown/uncertain.

Some source documents may contain violence, sexuality, abuse, death, extremism, discrimination, graphic descriptions, hateful content, or other sensitive material. Ignore sensitive content entirely: do not quote it, summarize it, classify it, reproduce it, or use it as evidence. Use only non-sensitive portions of the source. If the omitted sensitive material is necessary to establish a field or relationship, write unknown/uncertain rather than referring to or describing that material. Do not provide instructions, praise, advocacy, or speculation about harmful activity.

Assign one or more relationship labels from this taxonomy when the source supports multiple aspects; do not pad the list with unsupported labels: {taxonomy}
Assign one OR MORE shared-elements category from (only when clearly supported by the source; do not pad the list — most sources will need only one or two): {categories}

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

SOURCE RECORD AND LOCAL DOCUMENT EVIDENCE:
{source}
{document_text}
"""

GENERATION_PROMPT = """You are Prompt 2 for SETU-Culture. Generate EXACTLY THREE DISTINCT benchmark scenario/question packages using ONLY the source record and Prompt 1 extraction below. The source discusses a relationship between cultures, but it may not prove transmission. Preserve uncertainty and never add unsupported facts. Use unknown/uncertain when country, region, macro-region, or chronology is not supported. Vary the focus across the three packages while staying grounded in the same document.

Return ONLY a JSON array with exactly three objects. Every object must contain exactly these keys:
[
{{
  "culture_a_country_region": "",
  "culture_b_country_region": "",
  "scenario": "2-4 neutral sentences based on the relationship between Culture A and Culture B as supported by the source, without adding unsupported facts or outside knowledge",
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
  "explanation_question": "",
  "required_answer": "",
  "explanation_expected_reasoning": ""
}},
{{ ...same keys, a distinct scenario and question set... }},
{{ ...same keys, a distinct scenario and question set... }}
]

The MCQ must have one unambiguous answer, at least one overclaim distractor and one underclaim or wrong-direction distractor. Vary the position of the correct option across packages; do not systematically place it in option A. The true/false items must test different claims. Across the three packages, the `statement_is_true` values MUST be balanced: use either exactly two `false` and one `true`, or exactly one `false` and two `true`. Never return three true values or three false values. The explanation must name the relationship and explain continuity/change, or explain missing evidence for uncertain/parallel/false-friend cases.

SOURCE RECORD AND LOCAL DOCUMENT EVIDENCE:
{source}
PROMPT 1 EXTRACTION:
{extraction}
{document_text}
"""

FINAL_FIELDS = [
    "Author", "LLM_Used", "Instance_ID", "Culture_Source", "Culture_Source_Language",
    "Trustworthy_Class", "Question_Number", "Culture_A_Country_Region", "Culture_B_Country_Region",
    "Supporting_Evidences",
    "Contradictory/Refuting_Evidence", "Relationship_Label_Suggested", "Relationship_Label_Confirmed",
    "Culture_A_Period", "Culture_B_Period", "Shared_Elements", "Scenario", "MCQ_Question",
    "Option_A", "Option_B", "Option_C", "Option_D", "Option_A_Distractor_Type",
    "Option_B_Distractor_Type", "Option_C_Distractor_Type", "Option_D_Distractor_Type",
    "MCQ_Expected_Reasoning", "True/False_Statement_Question", "True/False_Statement_Type",
    "Statement_Is_True", "Required_Justification", "True/False_Expected_Reasoning",
    "Explanation_Question", "Required_Answer", "Explanation_Expected_Reasoning",
]

def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as f: return list(csv.DictReader(f))
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("records", data.get("sources", []))

def read_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists(): return {}
    return {str(row.get("record_id", "")): row for row in read_rows(path) if row.get("record_id")}

def resolve_local_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path

def extract_pdf_text(path: Path) -> tuple[str, str]:
    reader_cls = None
    try:
        from pypdf import PdfReader  # type: ignore
        reader_cls = PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
            reader_cls = PdfReader
        except ImportError:
            return "", "install pypdf or PyPDF2"
    try:
        pages = [f"[Page {i}]\n{page.extract_text() or ''}" for i, page in enumerate(reader_cls(str(path)).pages, 1)]
        text = "\n\n".join(pages).strip()
        return text, "success" if text else "empty_text"
    except Exception as exc:
        return "", f"failed: {exc}"

def local_document(item: dict[str, Any], manifest: dict[str, dict[str, Any]], max_chars: int) -> tuple[dict[str, Any], str]:
    entry = manifest.get(str(item.get("record_id", item.get("Instance_ID", ""))), {})
    path_value = entry.get("local_document_path", "")
    if not path_value: raise RuntimeError("local_document_path is empty in source_manifest.csv")
    path = resolve_local_path(path_value)
    if not path.is_file(): raise RuntimeError(f"local document does not exist: {path}")
    ext = (entry.get("file_extension") or path.suffix).lower()
    if ext != ".pdf": raise RuntimeError(f"expected a PDF local document, got {ext or 'unknown extension'}")
    text, status = extract_pdf_text(path)
    if status != "success": raise RuntimeError(f"PDF text extraction {status} for {path}")
    return {"manifest": entry, "path": str(path), "text_chars": len(text), "text": text[:max_chars]}, text[:max_chars]

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def safe_id(value: str) -> str: return re.sub(r"[^A-Za-z0-9_.-]", "_", value)

def prepare_batches(source_file: Path, batch_dir: Path, size: int) -> int:
    sources = read_rows(source_file)
    batch_dir.mkdir(parents=True, exist_ok=True)
    for offset in range(0, len(sources), size):
        batch_no = offset // size + 1
        batch = []
        for source in sources[offset:offset + size]:
            item = dict(source); item["Instance_ID"] = source["record_id"]; item["source_record_id"] = source["record_id"]
            batch.append(item)
        write_json(batch_dir / f"batch_{batch_no:04d}.json", batch)
        with (batch_dir / f"batch_{batch_no:04d}.csv").open("w", encoding="utf-8", newline="") as f:
            fields = list(batch[0].keys()) if batch else ["Instance_ID"]
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(batch)
    return (len(sources) + size - 1) // size

def clean_json(text: str) -> dict[str, Any]:
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.I)
    try: return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match: raise
        return json.loads(match.group(0))

def call_llm(prompt: str) -> dict[str, Any]:
    if OpenAI is None: raise RuntimeError("Install the openai package before an LLM stage")
    if not LLM_API_KEY: raise RuntimeError("Set LLM_API_KEY before an LLM stage")
    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, default_headers={"User-Agent": LLM_USER_AGENT, "x-stainless-lang": LLM_STAINLESS_LANG})
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(model=MODEL, max_tokens=4500, temperature=0.2, messages=[{"role":"user", "content":prompt}])
            return clean_json(response.choices[0].message.content or "")
        except Exception as exc:
            last = exc
            if attempt < MAX_RETRIES: time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} attempts: {last}")

def source_for_prompt(source: dict[str, Any], manifest_entry: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    result = dict(source)
    result["resolved_url"] = manifest_entry.get("resolved_url", "")
    result["local_document_path"] = manifest_entry.get("local_document_path", "")
    result["document_content_type"] = manifest_entry.get("content_type", "application/pdf")
    result["local_text_chars"] = document.get("text_chars", 0)
    result["description"] = (source.get("description") or "").strip()[:10000]
    return result

def randomize_mcq_options(generation: dict[str, Any]) -> dict[str, Any]:
    """Shuffle each option together with its distractor label before export."""
    result = dict(generation)
    pairs = [
        (result.get(f"option_{letter}"), result.get(f"option_{letter}_distractor_type"))
        for letter in "abcd"
    ]
    random.SystemRandom().shuffle(pairs)
    for letter, (option, distractor_type) in zip("abcd", pairs):
        result[f"option_{letter}"] = option
        result[f"option_{letter}_distractor_type"] = distractor_type
    return result

def truth_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true": return True
        if normalized == "false": return False
    return None

def flatten(item: dict[str, Any], extraction: dict[str, Any], generation: dict[str, Any], question_number: int) -> dict[str, Any]:
    def e(k, default=""): return extraction.get(k, default)
    def g(k, default=""): return generation.get(k, default)
    def relationship_labels() -> str:
        value = e("relationship_label_suggested")
        if isinstance(value, (list, tuple)):
            return "; ".join(str(label).strip() for label in value if str(label).strip())
        return str(value or "").strip()
    def country_region(prefix: str) -> str:
        combined = g(f"{prefix}_country_region")
        if combined: return combined
        country = g(f"{prefix}_country")
        region = g(f"{prefix}_region")
        return ", ".join(value for value in (country, region) if value)
    source_type = str(item.get("source_type", "")).strip().lower()
    source_id = str(item.get("source_id", "")).strip().lower()
    source_name = str(item.get("source_name", "")).strip().lower()
    evidence_class = str(item.get("evidence_class", "")).strip().lower()
    trustworthy_class = int(
        source_id == "openalex_scholarly"
        or source_type in {"openalex", "scholarly", "scholarly_work", "scholarly_works"}
        or "scholarly" in source_name
        or evidence_class == "scholarly_interpretation"
    )
    return {
        "Author": AUTHOR, "LLM_Used": MODEL, "Instance_ID": item["Instance_ID"], "Culture_Source": item.get("resolved_url", ""),
        "Culture_Source_Language": e("source_language"), "Trustworthy_Class": trustworthy_class, "Question_Number": question_number,
        "Culture_A_Country_Region": country_region("culture_a"), "Culture_B_Country_Region": country_region("culture_b"),
        "Supporting_Evidences": "", "Contradictory/Refuting_Evidence": "",
        "Relationship_Label_Suggested": relationship_labels(), "Relationship_Label_Confirmed": "", "Culture_A_Period": e("culture_a_period"),
        "Culture_B_Period": e("culture_b_period"), "Shared_Elements": e("shared_elements"), "Scenario": g("scenario"), "MCQ_Question": g("mcq_question"),
        "Option_A": g("option_a"), "Option_B": g("option_b"), "Option_C": g("option_c"), "Option_D": g("option_d"),
        "Option_A_Distractor_Type": g("option_a_distractor_type"), "Option_B_Distractor_Type": g("option_b_distractor_type"),
        "Option_C_Distractor_Type": g("option_c_distractor_type"), "Option_D_Distractor_Type": g("option_d_distractor_type"),
        "MCQ_Expected_Reasoning": g("mcq_expected_reasoning"), "True/False_Statement_Question": g("true_false_statement_question"),
        "True/False_Statement_Type": g("true_false_statement_type"), "Statement_Is_True": g("statement_is_true"), "Required_Justification": g("required_justification"),
        "True/False_Expected_Reasoning": g("true_false_expected_reasoning"), "Explanation_Question": g("explanation_question"),
        "Required_Answer": g("required_answer"), "Explanation_Expected_Reasoning": g("explanation_expected_reasoning"),
    }

def process_batch(batch_file: Path, out_dir: Path, manifest_file: Path, stage: str, dry_run: bool, max_text_chars: int) -> None:
    items = read_rows(batch_file); out_dir.mkdir(parents=True, exist_ok=True); (out_dir / "prompts").mkdir(exist_ok=True)
    write_json(out_dir / "prompts" / "prompt_1_extraction.txt.json", {"taxonomy":TAXONOMY,"shared_categories":SHARED_CATEGORIES,"template":EXTRACTION_PROMPT})
    write_json(out_dir / "prompts" / "prompt_2_generation.txt.json", {"template":GENERATION_PROMPT})
    extraction_path, generation_path = out_dir / "01_extractions.jsonl", out_dir / "02_generations.jsonl"
    extracted = {x["Instance_ID"]:x for x in read_rows(extraction_path)} if extraction_path.exists() else {}
    generated = {x["Instance_ID"]:x for x in read_rows(generation_path)} if generation_path.exists() else {}
    manifest = read_manifest(manifest_file)
    errors=[]
    dropped_low_confidence = set()
    for item in items:
        iid=item["Instance_ID"]
        try:
            document, document_text = local_document(item, manifest, max_text_chars)
            manifest_entry = document["manifest"]
            item["resolved_url"] = manifest_entry.get("resolved_url", "")
            source = source_for_prompt(item, manifest_entry, document)
        except Exception as exc:
            errors.append({"stage":"document","instance_id":iid,"error":str(exc)})
            continue
        if stage in ("extract","all") and iid not in extracted:
            prompt=EXTRACTION_PROMPT.format(taxonomy=json.dumps(TAXONOMY,ensure_ascii=False),categories=", ".join(SHARED_CATEGORIES),source=json.dumps(source,ensure_ascii=False),document_text=document_text)
            try:
                result={"Instance_ID":iid,"source_record_id":item.get("source_record_id",item.get("record_id","")),"source":source,"prompt":prompt}
                if dry_run: result["extraction"]={}
                else: result["extraction"]=call_llm(prompt)
                with extraction_path.open("a",encoding="utf8") as f: f.write(json.dumps(result,ensure_ascii=False)+"\n")
                extracted[iid]=result
            except Exception as exc: errors.append({"stage":"extract","instance_id":iid,"error":str(exc)})
        extraction = extracted.get(iid, {}).get("extraction", {})
        if isinstance(extraction, dict) and str(extraction.get("confidence", "")).strip().lower() == "low":
            dropped_low_confidence.add(iid)
            errors.append({"stage":"confidence_filter","instance_id":iid,"error":"Prompt 1 confidence is low; Prompt 2 was not executed and source was dropped"})
            continue
        if stage in ("generate","all") and not dry_run and iid in extracted and iid not in generated:
            inst=extracted[iid]; prompt=GENERATION_PROMPT.format(source=json.dumps(inst["source"],ensure_ascii=False),extraction=json.dumps(inst.get("extraction",{}),ensure_ascii=False),document_text=document_text)
            try:
                result={"Instance_ID":iid,"source_record_id":item.get("source_record_id",item.get("record_id","")),"prompt":prompt,"generation":call_llm(prompt)}
                with generation_path.open("a",encoding="utf8") as f: f.write(json.dumps(result,ensure_ascii=False)+"\n")
                generated[iid]=result
            except Exception as exc: errors.append({"stage":"generate","instance_id":iid,"error":str(exc)})
    final=[]
    for item in items:
        iid=item["Instance_ID"]
        if iid in dropped_low_confidence or iid not in extracted or iid not in generated: continue
        packages=generated[iid].get("generation", [])
        if isinstance(packages, dict): packages=[packages]
        if len(packages) != 3:
            errors.append({"stage":"generate_validation","instance_id":iid,"error":f"expected exactly 3 packages, received {len(packages)}"})
            continue
        truth_values = [truth_value(package.get("statement_is_true")) for package in packages if isinstance(package, dict)]
        true_count = sum(value is True for value in truth_values)
        if len(truth_values) != 3 or any(value is None for value in truth_values) or true_count not in (1, 2):
            errors.append({"stage":"generate_validation","instance_id":iid,"error":f"statement_is_true values must contain exactly one true and two false, or two true and one false; received {[package.get('statement_is_true') for package in packages]}"})
            continue
        final.extend(flatten(item, extracted[iid].get("extraction",{}), randomize_mcq_options(package), n) for n, package in enumerate(packages, 1))
    write_json(out_dir / "setu_culture_questions.json", final)
    with (out_dir / "setu_culture_questions.csv").open("w",encoding="utf8",newline="") as f: w=csv.DictWriter(f,fieldnames=FINAL_FIELDS); w.writeheader(); w.writerows(final)
    if errors: (out_dir / "errors.log").write_text("\n".join(json.dumps(e,ensure_ascii=False) for e in errors)+"\n",encoding="utf8")
    print(f"Processed {len(items)} sources; dropped {len(dropped_low_confidence)} low-confidence sources; generated {len(final)} complete items. Output: {out_dir}")

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--source-file",type=Path,default=DEFAULT_SOURCE_FILE); ap.add_argument("--manifest-file",type=Path,default=DEFAULT_MANIFEST); ap.add_argument("--batch-dir",type=Path,default=DEFAULT_BATCH_DIR); ap.add_argument("--prepare-batches",action="store_true"); ap.add_argument("--batch-file",type=Path); ap.add_argument("--out-dir",type=Path,default=DEFAULT_OUTPUT); ap.add_argument("--stage",choices=("extract","generate","all"),default="all"); ap.add_argument("--dry-run",action="store_true"); ap.add_argument("--batch-size",type=int,default=10); ap.add_argument("--max-text-chars",type=int,default=120000,help="maximum extracted PDF characters sent per prompt"); args=ap.parse_args()
    if args.prepare_batches:
        print(f"Created {prepare_batches(args.source_file,args.batch_dir,args.batch_size)} batches in {args.batch_dir}")
        return
    if not args.batch_file: ap.error("--batch-file is required unless --prepare-batches is used")
    process_batch(args.batch_file,args.out_dir,args.manifest_file,args.stage,args.dry_run,args.max_text_chars)
if __name__=="__main__": main()
