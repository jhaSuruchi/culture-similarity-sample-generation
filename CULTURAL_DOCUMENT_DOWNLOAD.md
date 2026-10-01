# SETU-Culture Stage 1: local document archive

Stage 1 uses a manual document-collection workflow. The source manifests were regenerated for the Suruchi English-only source set. Existing files under `cultural_crawl_4000/local_archive/document` were left untouched, but the regenerated manifest does not link them automatically. Fill in the URL and local path fields manually after verifying each document. This avoids treating DOI landing pages, paywalls, abstracts, or metadata pages as reliable full-text evidence.

`cultural_document_downloader.py` remains available as an optional automated helper for later use, but it is not required for the current manual workflow. No LLM is called and the benchmark extraction/generation pipeline is not modified.

## Identity and URL matching

The crawler's stable `record_id` is used throughout:

```text
record_id = future Instance_ID = local filename stem = manifest key
```

The manifest retains `original_url` from the source CSV. Fill `resolved_url` with the final public document link after checking it manually. Local processing matches the manually downloaded document using the same `record_id`.

Example mapping:

```text
record_id:       f825a3e4e6802e38c7ca6072
original_url:    https://doi.org/...
local_document_path: cultural_crawl_4000/local_archive/document/f8/f825a3e4e6802e38c7ca6072.pdf
file_extension:  .pdf
```

The SHA-256 hash in the manifest verifies the downloaded bytes.

## Manual completion workflow

The current manifest files are:

```text
cultural_crawl_4000/local_archive/source_manifest.csv
cultural_crawl_4000/local_archive/source_manifest.json
```

Both contain the same 882 unique English source records, in source order, from `cultural_crawl_4000/Division/Suruchi_english_only_sources.csv`. The manifests were initialized with these fields blank:

```text
local_document_path
file_extension
local_text_path
resolved_url
content_type
sha256
bytes_downloaded
http_status
retrieved_at
error
```

For each source:

1. Open `original_url`.
2. Download the document you are authorized to use.
3. Place it under `cultural_crawl_4000/local_archive/document/`.
4. Fill `local_document_path` with a path relative to the repository root, for example `cultural_crawl_4000/local_archive/document/f8/f825...pdf`.
5. Fill `file_extension`, including the leading dot, such as `.pdf`, `.html`, or `.txt`.
6. Fill `resolved_url` with the final public document URL. Optionally fill `content_type`, `sha256`, `bytes_downloaded`, and `retrieved_at`.
7. Set `download_status` to `manual_downloaded`.
8. Leave `local_text_path` and `extraction_status` as pending until the text-extraction stage is approved.

Do not change `record_id`, `source_id`, `original_url`, `external_id`, or the source metadata copied from `Suruchi_english_only_sources.csv`.

The JSON manifest must be kept synchronized with the CSV manifest. Until the next processing stage is approved, CSV is the convenient editing file and JSON is the machine-readable mirror.

## Validate the manual manifest

Run this check after editing:

```bash
python3 - <<'PY'
import csv
from pathlib import Path

root = Path('.')
path = root / 'cultural_crawl_4000/local_archive/source_manifest.csv'
with path.open(encoding='utf-8', newline='') as f:
    rows = list(csv.DictReader(f))

print('records:', len(rows))
print('unique record IDs:', len({r['record_id'] for r in rows}))
print('manual downloaded:', sum(r['download_status'] == 'manual_downloaded' for r in rows))
print('missing resolved URLs:', sum(not r['resolved_url'] for r in rows))
print('missing document paths:', sum(not r['local_document_path'] for r in rows))
print('missing extensions:', sum(not r['file_extension'] for r in rows))

for row in rows:
    if row['local_document_path']:
        file_path = root / row['local_document_path']
        if not file_path.exists(): print('MISSING FILE:', row['record_id'], file_path)
PY
```

## Optional automated helper

If you later decide to test automated retrieval again, install PDF support first:

```bash
python3 -m pip install pypdf
```

Scanned image-only PDFs require OCR and will typically report `empty_text`. OCR is not included in Stage 1 yet.

Then use the helper only in a separate output directory so the manually curated manifest is not overwritten:

```bash
python3 cultural_document_downloader.py \
  --source-file cultural_crawl_4000/Division/Suruchi_english_only_sources.csv \
  --out-dir /tmp/setu_automated_archive \
  --limit 10 \
  --sleep 1.0
```

## Output layout

```text
cultural_crawl_4000/local_archive/
  document/
    ab/
      abcdef...pdf
  source_manifest.json
  source_manifest.csv
```

Documents are sharded by the first two characters of `record_id` to avoid placing every file in one directory.

## Manifest fields

The manifest includes:

- `record_id`, source ID/name, title, language, evidence class, and tier;
- original and resolved URLs;
- local document and text paths;
- content type, extension, SHA-256, and downloaded byte count;
- HTTP, download, and extraction statuses;
- license metadata, external ID, retrieval time, and error message.

## Status interpretation

Common download statuses:

```text
pending_manual_download
manual_downloaded
```

Common extraction statuses:

```text
not_run
success
empty_text
failed: ...
```

Manual download success does not guarantee usable full text. DOI links may resolve to landing pages, publisher login pages, abstracts, or paywalls. Review the selected document before Stage 2.

## Rights and access

The script records the source's existing `rights_license` field but cannot determine whether downloading or redistributing full text is legally permitted in every case. Use downloaded material for authorized research, respect access controls and site terms, and do not bypass authentication or paywalls.

The downloader does not circumvent robots restrictions, login systems, CAPTCHAs, or subscription access. HTTP failures and access-denied pages remain visible in the manifest for review.
