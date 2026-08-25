# SETU-Culture source-pair pipeline

`setu_benchmark_pipeline.py` converts rows from
`setu_culture_outputs/benchmark_instance_template.csv` into extracted cultural
relationships and generated assessment questions.

## Execution flow

1. Read a template row and its existing `Instance_ID` and source URLs.
2. Resolve each URL in `setu_culture_outputs/all_records.csv` to obtain the
   crawled source text, language, region, macro-region, and evidence metadata.
3. Prompt 1 compares the two source records and extracts the suggested
   relationship label, earliest supported periods, shared-element category,
   transmission/localization evidence, uncertainty, and confidence.
4. Save each extraction under `01_extractions/<Instance_ID>.json` and append it
   to `01_extractions.jsonl` for resumable processing.
5. Prompt 2 uses only the template metadata and Prompt 1 extraction to create
   one scenario, MCQ, true/false item, and explanation question.
6. Save each generation under `02_generations/<Instance_ID>.json` and append it
   to `02_generations.jsonl`.
7. Flatten both stages into `final/setu_culture_questions.json` and
   `final/setu_culture_questions.csv`. Validator-only columns remain empty.

## Configuration

```bash
export LLM_API_KEY="..."
export LLM_BASE_URL="https://agentrouter.org/v1"
export LLM_MODEL="gpt-5.6-sol"
export SETU_AUTHOR="Validator name"
```

Install the transport library if needed:

```bash
pip install openai
```

## Commands

Prepare and inspect two source pairs without making API calls:

```bash
python Project/setu_benchmark_pipeline.py --limit 2 --stage extract --dry-run
```

Run Prompt 1 only:

```bash
python Project/setu_benchmark_pipeline.py --stage extract
```

Inspect the extraction files, then run Prompt 2 and build final exports:

```bash
python Project/setu_benchmark_pipeline.py --stage generate
```

Run the complete pipeline:

```bash
python Project/setu_benchmark_pipeline.py --stage all
```

Use `--limit N` for a pilot batch and `--out-dir PATH` for a different output
location. Reruns skip completed instance IDs. Failures are appended to
`errors.log` and can be retried by rerunning the affected stage.

## Notes

- The current benchmark template does not contain source-language columns.
  The script therefore resolves language from the matching `all_records.csv`
  URL. Empty crawled language values remain empty rather than being guessed.
- `Supporting_Evidences`, `Contradictory/Refuting_Evidence`, and
  `Relationship_Label_Confirmed` are intentionally left empty for validators.
- Many automatically proposed pairs are noisy lexical matches. Prompt 1 is
  explicitly required to return uncertain, parallel, or false-friend labels
  when the sources do not establish transmission.
