# SETU-Culture config-driven single-source crawling

`cultural_source_crawler.py` is the data-collection stage for the revised SETU-Culture workflow. It uses [`cultural_crawl_config.json`](./cultural_crawl_config.json), which defines geographic scope, aliases, languages, research concepts, cross-cultural queries, seed cases, source adapters, evidence classes, source tiers, and license expectations.

This crawler is separate from `setu_benchmark_pipeline.py`.

## No source pairs are generated

The crawler searches for individual sources that discuss relationships between two or more cultures. Each returned article, work, heritage record, museum object, or catalog item is saved as one independent source record.

For example, a query such as:

```text
Buddhism transmission India China Japan
```

may return one scholarly article. That article is saved as one record with its URL, description, evidence metadata, and query provenance. The crawler does not combine an India record with a China record, create pair IDs, or construct synthetic relationships.

The `seed_pairs` section is used only to create focused search queries and preserve provenance hints such as the intended shared element and relationship category. It does not generate pairs.

The intended later workflow is:

```text
one source record -> LLM evidence extraction -> scenario and question generation
```

No LLM is called by the crawler.

## Configuration

`cultural_crawl_config.json` is authoritative. It contains:

- `geographic_scope`: countries, macro-regions, aliases, languages, sub-regions, and local queries;
- `query_concepts`: research areas such as Buddhist transmission, syncretism, architecture, iconography, festivals, and performing arts;
- `cross_cultural_queries`: focused searches naming multiple cultures;
- `seed_pairs`: benchmark cases used as search and provenance hints;
- `sources`: enabled source adapters, evidence classes, tiers, languages, access levels, and license notes;
- `request_delay_seconds`: default delay between requests.

Each run copies the exact configuration to `crawl_config_snapshot.json` and records its SHA-256 hash in `crawl_report.json`.

## Query groups

| Group | Purpose |
|---|---|
| `cross_cultural` | Uses configured searches such as India-China-Japan Buddhism and Southeast Asian Ramayana retellings. |
| `seed_pairs` | Combines each seed case's two search descriptions into one source search. It does not create a pair. |
| `geographic_pairs` | Searches India against each comparison country across every configured concept; outputs remain single records. |
| `local_context` | Uses country-specific local queries such as Bodh Gaya and Ayodhya. |

The default is `cross_cultural,seed_pairs`.

## Sources and API keys

| Configured source | Evidence class / tier | API key |
|---|---|---|
| OpenAlex | Scholarly interpretation / 1 | No; `CONTACT_EMAIL` optional. |
| Crossref | Scholarly interpretation / 1 | No; `CONTACT_EMAIL` optional. |
| Wikidata | Institutional heritage description / 2 | No; public endpoint limits apply. |
| UNESCO World Heritage | Institutional heritage description / 2 | No; attribution and redistribution restrictions apply. |
| Metropolitan Museum | Institutional heritage description / 2 | No; check public-domain status per object. |
| Europeana | Institutional heritage description / 2 | `EUROPEANA_API_KEY` required. |
| Internet Archive | Primary evidence/catalog metadata / 1 | No; check each item license. |
| Wikipedia English/Japanese/Indonesian | Popular secondary / 4 | No; rate limits apply. |
| Configured heritage URLs | Institutional heritage description / 2 | No; rights vary by site. |

The main config crawler does not invoke the YouTube adapter. Use `youtube_source_crawler.py` with a YouTube Data API key to collect paginated YouTube video metadata. YouTube records remain popular-secondary evidence and should be corroborated for strong historical claims. RSS and the placeholder OAI-PMH repository remain disabled.

## Crawl YouTube

The standalone YouTube crawler searches every configured cultural query group and follows all available result pages by default. It does not use a discovery-only mode and does not download video or audio.

```bash
export YOUTUBE_API_KEY="your-youtube-data-api-v3-key"
python3 youtube_source_crawler.py \
  --out-dir cultural_crawl_youtube \
  --query-groups cross_cultural,seed_pairs,geographic_pairs,local_context
```

Use `--max-pages` when you need a bounded test run. The API has quota limits; each search page and video-details request consumes YouTube Data API quota. Review the generated `crawl_report.json` and rights metadata before using records as benchmark evidence.

## Requirements and environment

The crawler uses Python's standard library only and requires Python 3.10+.

```bash
export CONTACT_EMAIL="you@example.org"
export EUROPEANA_API_KEY="your-europeana-key"
export CRAWLER_USER_AGENT="SETU-Culture-Bot/1.0 (research; contact via CONTACT_EMAIL env var)"
```

`CONTACT_EMAIL` is sent to Crossref/OpenAlex when set. Europeana is skipped and reported unless its key is available.

## Run a focused crawl

```bash
python3 cultural_source_crawler.py \
  --config cultural_crawl_config.json \
  --out-dir cultural_crawl_outputs \
  --query-groups cross_cultural,seed_pairs \
  --limit-per-query 5
```

## Run a small test crawl

```bash
python3 cultural_source_crawler.py \
  --config cultural_crawl_config.json \
  --out-dir cultural_crawl_test \
  --sources crossref_scholarly,openalex_scholarly \
  --query-groups cross_cultural,seed_pairs \
  --limit-per-query 2 \
  --max-queries 3 \
  --sleep 1.5
```

`--sources` takes configured source IDs. Disabled sources are excluded automatically. `--max-queries 0` means all selected queries.

## Expand geographic and local searches

```bash
python3 cultural_source_crawler.py \
  --config cultural_crawl_config.json \
  --out-dir cultural_crawl_geographic \
  --query-groups cross_cultural,seed_pairs,geographic_pairs,local_context \
  --limit-per-query 3 \
  --sleep 1
```

Geographic expansion can create many searches, so begin with a low result limit and use separate output directories for separate snapshots.

## Recommended full crawl: target at least 2,000 records

Because a Europeana API key is available, the recommended full run uses Crossref, OpenAlex, and Europeana. Export the credentials first:

```bash
export EUROPEANA_API_KEY="your-europeana-key"
export CONTACT_EMAIL="your-email@example.com"
```

Run this exact one-line command to avoid shell line-continuation problems:

```bash
python3 cultural_source_crawler.py --config cultural_crawl_config.json --out-dir cultural_crawl_2000 --sources "crossref_scholarly,openalex_scholarly,europeana_objects" --query-groups "cross_cultural,seed_pairs,geographic_pairs,local_context" --limit-per-query 25 --sleep 0.8
```

The complete configuration produces 140 queries. This command requests up to 10,500 candidates before deduplication: 140 queries × 25 results × 3 sources. Crossref and OpenAlex provide scholarly records; Europeana adds institutional cultural-heritage records.

The final unique count may be lower because one source can match several queries. Do not use `--max-queries` for the full crawl; that option intentionally limits test runs.

If the final count remains below 2,000, run a larger crawl into a new directory:

```bash
python3 cultural_source_crawler.py --config cultural_crawl_config.json --out-dir cultural_crawl_4000 --sources "crossref_scholarly,openalex_scholarly,europeana_objects" --query-groups "cross_cultural,seed_pairs,geographic_pairs,local_context" --limit-per-query 40 --sleep 1.0
```

### Run without Europeana

If the Europeana key is unavailable, use the two scholarly indexes:

```bash
python3 cultural_source_crawler.py --config cultural_crawl_config.json --out-dir cultural_crawl_scholarly --sources "crossref_scholarly,openalex_scholarly" --query-groups "cross_cultural,seed_pairs,geographic_pairs,local_context" --limit-per-query 25 --sleep 0.8
```

Confirm that Europeana was included:

```bash
python3 - <<'PY'
import json

report = json.load(open("cultural_crawl_2000/crawl_report.json"))
print("Records:", report["record_count"])
print("Sources:", report["sources"])
print("Europeana key used:", report["europeana_api_key_used"])
print("Errors:", len(report["errors"]))
print("Skipped:", report["skipped_sources"])
PY
```

You should see `Europeana key used: True`. To inspect per-source counts:

```bash
python3 - <<'PY'
import csv
from collections import Counter

with open("cultural_crawl_2000/cultural_sources.csv", encoding="utf-8") as f:
    counts = Counter(row["source_id"] for row in csv.DictReader(f))
for source, count in counts.most_common():
    print(f"{source}: {count}")
PY
```

## Output files

```text
cultural_sources.json          JSON array of independent source records
cultural_sources.jsonl         One source record per line
cultural_sources.csv           Spreadsheet-friendly export
crawl_config_snapshot.json     Exact configuration used
crawl_report.json              Counts, queries, source status, errors, config hash
```

There is intentionally no pair file in this workflow.

## Record fields

Records include source identity and URL; evidence class and tier; title, bounded description, authors, publisher, date, and language; query ID/group/text; target cultures; seed ID and configured provenance hints; matched queries after deduplication; rights/access metadata; external ID; and retrieval timestamp.

Configured relationship fields are hints for review, not validated conclusions.

## Errors and review

Requests retry up to four times with backoff. Non-fatal failures are recorded in `crawl_report.json`. HTTP 429 responses may require a larger `--sleep`, a smaller `--limit-per-query`, `CONTACT_EMAIL`, or a later rerun.

The crawler does not call an LLM, generate pairs, infer ancestry or transmission, verify chronology, validate configured relationship labels, or replace expert/community review. Check source quality and licensing before using records for benchmark generation.
