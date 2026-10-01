# YouTube Transcripts and Batchwise Question Generation

This workflow uses the 1,797 unique YouTube source records in `cultural_crawl_youtube/`.

It has two preparation stages:

1. Download and track one transcript per YouTube source link.
2. Divide the source records into batches of 100 for later question generation.

The transcript downloader stores the source link and transcript in the same record, so every transcript remains traceable to its YouTube video.

## Files and scripts

```text
youtube_transcript_downloader.py   Fetches and tracks transcripts
divide_youtube_batches.py          Creates 100-record JSON/CSV batches
cultural_crawl_youtube/
  cultural_sources.json             1,797 source records
  transcripts/
    transcripts.json                Transcript manifest as a JSON array
    transcripts.jsonl               One transcript record per line
    transcripts.csv                 Spreadsheet-compatible transcript manifest
  batches_100/
    batch_0001.json                 100 source records
    batch_0001.csv                  Same batch in CSV form
    ...
    batch_0018.json                 Final batch of 97 records
    batch_0018.csv
```

The existing YouTube source files are not overwritten.

## Install the transcript dependency

The downloader uses `youtube-transcript-api`:

```bash
python3 -m pip install youtube-transcript-api
```

Use the same Python environment for installation and execution. The package accesses public YouTube transcript endpoints; it does not use the YouTube Data API key.

## Download transcripts

Run the full transcript collection:

```bash
python3 youtube_transcript_downloader.py \
  --source-file cultural_crawl_youtube/cultural_sources.json \
  --out-dir cultural_crawl_youtube/transcripts \
  --languages en,hi,sa,ne,si,zh,ja,ko,id,th,km,lo,my,ms,vi \
  --sleep 0.2
```

The downloader processes each source's `external_id` (the YouTube video ID) and preserves:

- `record_id`
- `external_id`
- `source_link`
- video title and source language
- selected transcript language
- transcript type (`manual`, `generated`, or `unknown`)
- full transcript text
- timestamped transcript segments
- `download_status`, retrieval time, and error text

The output row has this core provenance relationship:

```text
source_link -> YouTube URL used for the source record
external_id -> YouTube video ID
transcript -> transcript fetched for that video ID
```

## Resuming and retrying

The downloader writes output after each processed record. If the process stops, rerun the same command; existing records in `transcripts.jsonl` are reused.

To retry every record, including previously successful records:

```bash
python3 youtube_transcript_downloader.py \
  --source-file cultural_crawl_youtube/cultural_sources.json \
  --out-dir cultural_crawl_youtube/transcripts \
  --redownload
```

To test the first 10 records without starting the full collection:

```bash
python3 youtube_transcript_downloader.py \
  --source-file cultural_crawl_youtube/cultural_sources.json \
  --out-dir /tmp/youtube_transcripts_test \
  --limit 10
```

Transcript availability is not guaranteed. Videos may have no captions, disabled captions, language mismatches, region restrictions, age restrictions, removed videos, or API-library access failures. These records remain in the manifest with `download_status=error` and an explanatory `error` field.

## Create batches of 100

The source crawl contains 1,797 unique video records. Create the batches with:

```bash
python3 divide_youtube_batches.py \
  --source-file cultural_crawl_youtube/cultural_sources.json \
  --out-dir cultural_crawl_youtube/batches_100 \
  --batch-size 100
```

Current result:

```text
Total records: 1,797
Batches: 18
Full batches: 17 x 100 records
Final batch: 97 records
```

The splitter writes both JSON and CSV for every batch. Batch order follows the order in `cultural_sources.json`.

## Joining batches to transcripts

Question generation should join each batch record to the transcript manifest by `record_id` or `external_id`, not by title. A generation input should contain at least:

```json
{
  "record_id": "...",
  "source_link": "https://www.youtube.com/watch?v=...",
  "title": "...",
  "description": "...",
  "transcript_language": "en",
  "transcript_type": "manual",
  "transcript": "..."
}
```

Only records with `download_status=downloaded` and non-empty `transcript` should be sent for transcript-grounded generation. Keep failed records for retry and audit; do not silently replace a missing transcript with metadata-only prompting.

## Batchwise question generation

The current `setu_benchmark_pipeline.py` is designed for local PDF documents and reads `local_document_path` from `source_manifest.csv`. It does not directly consume `transcripts.jsonl` or `batches_100/*.json`. Therefore, do not pass the YouTube batches to that pipeline as though they were PDF batches.

A transcript-aware generation adapter should process one batch at a time using this sequence:

1. Read one `batches_100/batch_NNNN.json` file.
2. Join its rows to `transcripts/transcripts.jsonl` by `record_id`.
3. Skip and log rows without a downloaded transcript.
4. Run Prompt 1 on the transcript and source metadata.
5. Drop a source when Prompt 1 returns `confidence: low`.
6. Run Prompt 2 only for accepted sources.
7. Require exactly three packages per accepted source.
8. Preserve the source `source_link` in every generated row.
9. Write separate JSON/CSV output for that batch and an `errors.log`.

The generated schema should retain the existing benchmark fields, including:

```text
Culture_Source
Culture_Source_Language
Trustworthy_Class
Question_Number
Culture_A_Country_Region
Culture_B_Country_Region
Shared_Elements
Relationship_Label_Suggested
Scenario
MCQ_Question
Option_A ... Option_D
True/False_Statement_Question
Explanation_Question
```

For YouTube records, `Culture_Source` should be the `source_link`, and `Trustworthy_Class` should remain `0` unless an independent review process assigns a different class. YouTube records are popular-secondary material and should not be treated as scholarly evidence solely because a video discusses a scholarly topic.

## Recommended output layout

```text
setu_youtube_generated/
  batch_0001/
    questions.json
    questions.csv
    errors.log
  batch_0002/
    questions.json
    questions.csv
    errors.log
  ...
  batch_0018/
```

Use a separate output directory per batch so retries do not overwrite the source transcript manifest or another batch's results.

## Validation checklist

Before generation:

```bash
python3 - <<'PY'
import csv
import json
from pathlib import Path

source = json.loads(Path('cultural_crawl_youtube/cultural_sources.json').read_text())
transcripts = [json.loads(line) for line in Path('cultural_crawl_youtube/transcripts/transcripts.jsonl').read_text().splitlines() if line.strip()] if Path('cultural_crawl_youtube/transcripts/transcripts.jsonl').exists() else []
batches = sorted(Path('cultural_crawl_youtube/batches_100').glob('batch_*.json'))
sizes = [len(json.loads(path.read_text())) for path in batches]
print('source records:', len(source))
print('transcript records:', len(transcripts))
print('batches:', len(batches), 'sizes:', sizes)
print('downloaded transcripts:', sum(row.get('download_status') == 'downloaded' for row in transcripts))
print('transcript failures:', sum(row.get('download_status') == 'error' for row in transcripts))
PY
```

The expected batch sizes for the current crawl are 17 batches of 100 and one batch of 97. Review transcript failure counts before starting LLM generation, because unavailable transcripts reduce the number of sources that can produce questions.

## Rights and responsible use

The downloader stores transcript text for authorized research workflows. YouTube videos and transcripts may be copyrighted, user-generated, or sensitive. Respect the video's terms, applicable copyright and privacy rules, and platform restrictions. Do not redistribute transcript text or generated material beyond the rights and review permissions available for the source.
