# YouTube Crawling

`youtube_source_crawler.py` is the standalone YouTube collection stage for SETU-Culture. It searches YouTube for the cultural research queries in `cultural_crawl_config.json` and saves video metadata in the same source-record format used by the other crawlers.

The crawler does not download video or audio. It collects metadata from the YouTube Data API v3, including the public video URL, title, description, channel, publication date, language, tags, duration, and available engagement counts.

## Requirements

You need a YouTube Data API v3 key with the YouTube Data API enabled in the associated Google Cloud project.

```bash
export YOUTUBE_API_KEY="your-youtube-data-api-v3-key"
```

The script uses Python's standard library and requires Python 3.10 or newer.

## Basic command

```bash
python3 youtube_source_crawler.py \
  --out-dir cultural_crawl_youtube \
  --query-groups cross_cultural,seed_pairs,geographic_pairs,local_context
```

The `--query-groups` value must remain a single shell argument. Do not insert spaces inside a group name such as `local_context` or `geographic_pairs`.

## Parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| `--api-key` | `$YOUTUBE_API_KEY` | YouTube Data API v3 key. The command stops if neither this option nor the environment variable is set. |
| `--config` | `cultural_crawl_config.json` | JSON configuration containing geographic scope, concepts, cross-cultural queries, and seed pairs. |
| `--out-dir` | `youtube_crawl_outputs` | Directory for CSV, JSON, JSONL, report, and config snapshot outputs. |
| `--query-groups` | `cross_cultural,seed_pairs,geographic_pairs,local_context` | Comma-separated query groups to crawl. |
| `--max-pages` | `0` | Maximum search-result pages per query. `0` follows all pages available from the API. |
| `--max-results-per-page` | `50` | Results requested per search page. Valid range is 1-50. |
| `--sleep` | `0.2` | Seconds to wait between paginated requests for the same query. |

There is no discovery-only parameter or mode. Every returned YouTube result is written as a source record with `source_id=youtube_videos`. YouTube remains classified as popular-secondary material (`source_tier=4`), so strong historical claims should be corroborated with scholarly, institutional, primary, or community evidence.

## Query groups

The crawler builds queries from the project configuration:

- `cross_cultural`: six configured cross-cultural queries such as Buddhism transmission, Ramayana retellings, Garuda, and solar kingship.
- `seed_pairs`: six configured cultural seed cases, expanded with transmission, adaptation, similarity, and origin terms.
- `geographic_pairs`: each non-India geographic scope entry combined with the nine configured concepts. With the current configuration this produces 126 queries.
- `local_context`: configured local queries for geographic scope entries that define them. With the current configuration this produces two India queries.

With the current configuration, selecting all four groups creates 140 unique queries:

```text
6 cross-cultural + 6 seed-pair + 126 geographic-pair + 2 local-context = 140 queries
```

## API behavior and quota

For each query, the script calls `search.list` with `type=video` and follows `nextPageToken` until there are no more pages or `--max-pages` is reached. It then calls `videos.list` for the returned video IDs to obtain metadata and statistics.

YouTube Data API quota is important:

- Each `search.list` request consumes 100 quota units.
- `videos.list` requests consume quota as well, typically much less than search.
- The default crawl can reach the project's daily search quota quickly because it runs many queries and follows pagination.
- HTTP 429 quota errors are recorded per query in `crawl_report.json`; records collected before quota exhaustion are still written.

For a small test, limit both pages and results:

```bash
python3 youtube_source_crawler.py \
  --out-dir cultural_crawl_youtube_test \
  --query-groups cross_cultural \
  --max-pages 1 \
  --max-results-per-page 10
```

## Current crawl totals

The existing crawl in `cultural_crawl_youtube/` was run with:

```text
query groups: cross_cultural, geographic_pairs, local_context, seed_pairs
queries constructed: 140
max_pages: 0 (all available pages)
max_results_per_page: 50
request delay: 0.2 seconds
pages crawled successfully: 134
search results seen: 2,229
video detail records seen: 2,229
unique video records written: 1,797
query errors: 45
```

The errors were YouTube quota-exhaustion responses after the daily `Search Queries` limit was reached. They are listed in:

```text
cultural_crawl_youtube/crawl_report.json
```

The output therefore contains all records collected before quota exhaustion, not a complete traversal of all 140 queries.

## Output files

The output directory contains:

```text
cultural_sources.csv             Spreadsheet-compatible source records
cultural_sources.json            Pretty-printed source-record array
cultural_sources.jsonl           One source record per line
crawl_report.json                Counts, parameters, and per-query errors
crawl_config_snapshot.json       Exact configuration used for the crawl
```

Each source record uses the shared crawler schema. YouTube-specific values are represented as follows:

| Field | YouTube value |
| --- | --- |
| `source_id` | `youtube_videos` |
| `source_type` | `youtube` |
| `evidence_class` | `popular_secondary_material` |
| `source_tier` | `4` |
| `url` | `https://www.youtube.com/watch?v=VIDEO_ID` |
| `external_id` | YouTube video ID |
| `publisher` | `YouTube` |
| `authors` | Channel title |
| `rights_license` | `varies_by_video_check_rights` |
| `access_level` | `metadata_only` |

The description includes the video description plus available API metadata such as channel ID, category, duration, view count, like count, and comment count.

## Rights and evidence use

The crawler stores metadata and public links; it does not grant redistribution rights for videos, thumbnails, transcripts, or other copyrighted material. Check the individual video's terms and rights before downloading, quoting, or redistributing content.

YouTube records are useful for documenting public cultural communication and community media, but a video alone should not be treated as proof of historical transmission. Preserve the source tier and corroborate important claims with stronger evidence.

## Reproducibility

Every run writes the exact configuration snapshot and runtime parameters to `crawl_report.json`. Keep that report with the generated source files. A later run may return different results because YouTube search ranking, availability, metadata, and quota state change over time.
