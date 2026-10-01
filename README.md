# SETU-Culture

SETU-Culture is a benchmark pipeline for evaluating whether language and multimodal models can reason about cultural relationships across regions. It distinguishes documented transmission, local adaptation, religious syncretism, parallel motifs, uncertain claims, and superficial resemblance.

The project is designed around an important safeguard: cultural similarity does not, by itself, prove historical borrowing. Automatically proposed links must therefore remain evidence-grounded and be reviewed by humans before benchmark use.

## What the pipeline does

`setu_benchmark_pipeline.py` turns paired source records into assessment items in two LLM stages:

1. Prompt 1 resolves both source URLs, supplies their metadata and crawled descriptions, and extracts:
   - a relationship label;
   - earliest supported periods;
   - one shared-element category;
   - transmission and local-transformation summaries;
   - uncertainty and confidence.
2. Prompt 2 uses only the pair metadata and Prompt 1 output to generate:
   - a neutral scenario;
   - a four-option multiple-choice question;
   - a true/false item with required justification;
   - an explanation question and expected answer.
3. The results are flattened into JSON and CSV exports.

The pipeline is file-backed and resumable. Completed `instance_id` values are skipped on reruns, and failures are appended to `errors.log`.

## Relationship taxonomy

| Label | Meaning |
| --- | --- |
| `A_documented_transmission` | Movement through trade, pilgrimage, translation, migration, conquest, diplomacy, or missionary activity. |
| `B_localization_adaptation` | A transmitted element is retained but renamed, reinterpreted, visually transformed, or embedded in local practice. |
| `C_syncretism_religious_integration` | Elements from multiple traditions combine into a new local form. |
| `D_parallel_motif_convergent_similarity` | A shared structural idea without evidence that one tradition came from the other. |
| `E_contested_or_uncertain_relationship` | A proposed link has incomplete, disputed, or chronologically unclear evidence. |
| `F_false_friend_superficial_resemblance` | Items look similar but differ in meaning, function, chronology, or origin. |

## Repository layout

```text
setu_benchmark_pipeline.py          LLM extraction and question-generation script
SETU_BENCHMARK_PIPELINE.md          Concise pipeline notes and command reference
cultural_similarity_llm.docx       Benchmark concept and methodology brief
setu_culture_outputs/
  all_records.csv/jsonl              Crawled source records
  benchmark_instance_template.csv   Paired source instances
  cultural_links.csv/jsonl           Proposed cultural links
  setu_culture.sqlite3               SQLite copy of the collection snapshot
  evidence_policy.json               Evidence classes, tiers, and taxonomy
  evidence_matrix.csv                Evidence coverage summary
  geographic_coverage_gaps.csv      Coverage-gap report
  source_registry_snapshot.csv      Sources used by the collector
```

The checked-in output snapshot contains collected records and proposed links. Links are intended to remain pending human review; it is not a fully validated benchmark release.

## Requirements

- Python 3.10 or newer
- An API key for an OpenAI-compatible endpoint
- The `openai` Python package

Install the client library:

```bash
python3 -m pip install openai
```

## Configure the LLM endpoint

The current defaults target AgentRouter:

```bash
export LLM_API_KEY="your-agentrouter-key"
export LLM_BASE_URL="https://agentrouter.org/v1"
export LLM_MODEL="gpt-5.6-sol"
export SETU_AUTHOR="Validator or author name"
# Optional AgentRouter client fingerprints
export LLM_USER_AGENT="Kilo-Code/5.3.0"
export LLM_STAINLESS_LANG="python"
```

These values can be overridden through environment variables. The endpoint must support the OpenAI Chat Completions-compatible interface used by the script.

The script sends the optional AgentRouter-compatible client fingerprints through
the OpenAI SDK's `default_headers`. Keep `LLM_MODEL` as the exact model ID
returned by the router's `/models` endpoint. For example, `gpt-5.6-sol` and
`gpt5.6-sol` are different strings; do not switch between them unless the
router explicitly lists both.

Before running a batch, it is useful to verify authentication independently:

```bash
curl -i "${LLM_BASE_URL}/models" \
  -H "Authorization: Bearer ${LLM_API_KEY}"
```

## Run two sample instances

From the repository root:

```bash
python3 setu_benchmark_pipeline.py \
  --input-dir setu_culture_outputs \
  --out-dir setu_culture_generated \
  --stage all \
  --limit 2
```

The final files are:

```text
setu_culture_generated/final/setu_culture_questions.json
setu_culture_generated/final/setu_culture_questions.csv
```

## Dry run without API calls

Use dry-run mode to prepare and inspect Prompt 1 inputs without contacting the model:

```bash
python3 setu_benchmark_pipeline.py \
  --input-dir setu_culture_outputs \
  --out-dir setu_culture_dry_run \
  --stage extract \
  --limit 2 \
  --dry-run
```

This writes the prepared extraction records and prompt templates, but does not generate questions.

## Run stages separately

Extract relationship information only:

```bash
python3 setu_benchmark_pipeline.py \
  --input-dir setu_culture_outputs \
  --out-dir setu_culture_generated \
  --stage extract
```

Generate questions from completed extractions and write final exports:

```bash
python3 setu_benchmark_pipeline.py \
  --input-dir setu_culture_outputs \
  --out-dir setu_culture_generated \
  --stage generate
```

Use `--limit N` for a pilot batch and `--out-dir PATH` to keep separate runs in separate directories.

## Intermediate and final outputs

For an output directory such as `setu_culture_generated`, the script creates:

```text
prompts/prompt_1_extraction.txt
prompts/prompt_2_generation.txt
01_extractions.jsonl
01_extractions/<Instance_ID>.json
02_generations.jsonl
02_generations/<Instance_ID>.json
final/setu_culture_questions.json
final/setu_culture_questions.csv
errors.log                         created only when a stage fails
```

`Supporting_Evidences`, `Contradictory/Refuting_Evidence`, and `Relationship_Label_Confirmed` are intentionally left empty for validator completion. The generated relationship is a suggestion, not a final gold label.

## Evidence and validation policy

The source snapshot separates evidence into:

- primary evidence;
- scholarly interpretation;
- institutional heritage description;
- community testimony;
- popular secondary material.

Source tiers distinguish primary/peer-reviewed material, institutional sources, community/local documentation, and popular-secondary material. YouTube, Wikipedia, and similar popular sources can be collected as source records but should be corroborated rather than treated as sufficient evidence for strong historical claims. Automatically generated pairs—especially lexical/domain matches—require expert or community review, particularly for sensitive or contested cultural claims.

## Current limitations

- Many proposed pairs are noisy lexical matches rather than documented relationships.
- The checked-in links are pending human review.
- The template may not contain source-language fields; the script falls back to language metadata from `all_records.csv`.
- Missing crawled descriptions are passed to the model as metadata-only records and should produce explicit uncertainty.
- The pipeline does not perform automatic factual validation of model outputs.
- External collection sources can be rate-limited or return unavailable records; see `run_report.json` for the collection snapshot’s errors.

## Troubleshooting

### `401 UNAUTHENTICATED` or `unauthorized client detected`

The request reached the configured provider but the key was rejected. Check that the key belongs to the configured endpoint, has no surrounding whitespace, and is authorized for the requested model. Test `/models` with `curl` before rerunning the pipeline.

### `openai package is required`

Install the dependency:

```bash
python3 -m pip install openai
```

### Empty final exports

The final files contain only instances for which both extraction and generation completed. Inspect `errors.log`, fix the API or input problem, and rerun the same stage.

## License and source rights

Source rights vary by provider and record. Consult each record’s rights/license metadata before redistributing source text or benchmark material. The pipeline stores source metadata and descriptions from a heterogeneous collection and does not grant additional rights over those sources.
