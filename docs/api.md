# HTTP API

Base URL: `http://localhost:8460` (Docker) or the Vite dev server on `:5460`, which proxies `/api`.
All responses are JSON unless stated. Errors use FastAPI's shape: `{"detail": "message"}`.

| Status | Meaning |
|---|---|
| 400 | Bad upload: no files, conflicting or duplicate paths |
| 404 | Unknown or expired `report_id` (analyse again), or no benchmark run yet |
| 413 | Upload over the limit (50 MB by default, `RAGCOMPASS_MAX_UPLOAD_MB`) |
| 422 | Invalid parameter: unknown file, strategy not valid for the file, size or overlap out of range |
| 501 | Feature needs the optional `ragcompass[bench]` extra (dense embeddings) |

Every endpoint that takes `lang` accepts `en` (default) or `es`.

## Reports and `report_id`

Each analysis is kept in memory so the chunk explorer, the benchmark, the projection and the exporters can work on
it later. Reports live for 30 minutes (`RAGCOMPASS_STORE_TTL`, seconds) and at most 32 are kept
(`RAGCOMPASS_STORE_ITEMS`), least recently used first out. Nothing is written to disk. A restart forgets them all,
so a client that gets a 404 should run the analysis again.

### `POST /api/analyze`

Multipart upload, field name `files`, repeated. A folder upload sends each file with its relative path as the file
name (`kb/manual.pdf`); a single top-level folder becomes the report root.

Query: `format=json|md|yaml` (default `json`), `lang`, `llm_summary=false`.

Returns the `Report` (below). `report.id` is the `report_id`.

### `POST /api/sample`

Analyses the bundled sample corpus. Same query parameters and response as `/api/analyze`.

### `GET /api/report/{report_id}`

The stored report. Query: `format=json|md|yaml`, `lang`. If a benchmark has run, `report.bench` holds it and the
chunking, top-k and hybrid recommendations carry their measured basis (see the benchmark section).

### `POST /api/render`

Body: a `Report` the client already has. Query: `format=md|yaml` (required), `lang`. Returns `text/plain`.

### `Report` fields the web uses

```jsonc
{
  "generator": "ragcompass",
  "version": "0.1.0",
  "lang": "en",
  "id": "9f2c4e1a7b3d5e60",                // report_id
  "summary": { "root": "sample-corpus", "files": 9, "analysed": 9, "tokens": 4624, "pages": 4,
               "kinds": { "pdf_text": 1, "...": 1 }, "languages": { "en": 3, "es": 1 }, "tokenizer": "cl100k_base" },
  "documents": [ {
      "path": "onboarding-handbook.md",      // use as `file` in the endpoints below
      "kind": "markdown",                    // pdf_text, pdf_scanned, pdf_mixed, docx, markdown, html, csv, xlsx, code, text, image, unsupported
      "pages": null, "scanned_pages": 0, "chars": 3010, "tokens": 622, "language": "en",
      "headings": 6, "tables": 1, "table_rows": 3, "list_items": 7, "code_blocks": 1, "images": 0,
      "identifiers": { "codes": 3, "dates": 0, "numbers": 5, "per_1k_tokens": 12.9, "codes_per_1k_tokens": 4.8 },
      "error": null, "warnings": []
  } ],
  "simulations": [ {
      "group": "documents",                  // documents, tables or code
      "strategy": "heading", "size": 256, "overlap": 0,
      "chunks": 15, "tokens": { "min": 20, "p50": 197, "p95": 243, "max": 251, "mean": 171.3 },
      "total_tokens": 2570, "overhead_pct": 0.0,
      "sentence_cut_pct": 0.0, "table_cut_pct": 0.0, "orphan_heading_pct": 0.0, "code_cut_pct": 0.0,
      "tiny_pct": 13.3, "damage": 13.3,
      "histogram": { "edges": [0, 26, 51, 77, 102, 128, 154, 179, 205, 230, 256], "counts": [1, 0, 1, 0, 1, 2, 1, 3, 2, 4] }
  } ],
  "recommendations": [ {
      "key": "chunking.documents",
      "value": { "strategy": "heading", "size": 256, "overlap": 0 },
      "reason": "...",                        // in `lang`
      "reason_i18n": { "en": "...", "es": "..." },
      "reason_parts": [ { "id": "chunking.size.structured", "params": { "share": 100, "median": 75 } } ],
      "evidence": { "chunks": 15, "damage": 13.3, "fixed_baseline_damage": 191.0 },
      "basis": "rule-based"                   // or "measured" after a benchmark
      // keys: parser.<kind>, chunking.<group>, vectors, embedding.dimension, embedding.quantization,
      // embedding.cost, retrieval.retriever (bm25|dense|hybrid), retrieval.hybrid_bm25, retrieval.top_k,
      // retrieval.reranker, metadata
  } ],
  "index": [ { "dimension": 1024, "vectors": 30, "float32_bytes": 122880, "int8_bytes": 30720, "hnsw_overhead_bytes": 3840 } ],
  "costs": [ { "model": "openai text-embedding-3-small", "usd_per_million": 0.02, "tokens": 5956, "usd": 0.0001 } ],
  "config": { "...": "the ragcompass.yaml content" },
  "bench": null                             // BenchResult once a benchmark has run
}
```

Histogram: ten equal bins from 0 to the target `size`, in tokens. `edges` has 11 values and `counts` 10; the last bin
also counts chunks larger than `size` (a row group with its repeated header can be).

## Chunk explorer

### `GET /api/report/{report_id}/chunks`

| Query | Default | Notes |
|---|---|---|
| `file` | required | `report.documents[].path` of a file with text (images and fully scanned PDFs return 422) |
| `strategy` | recommended for the file's group | documents: `heading`, `page`, `recursive`, `fixed`; tables: `row`, `recursive`, `fixed`; code: `recursive`, `fixed` |
| `size` | recommended | tokens, 16..8192 |
| `overlap` | recommended if the strategy is the recommended one, else 0 | tokens, `0 <= overlap < size`; forced to 0 for `heading`, `page` and `row` |

```jsonc
{
  "report_id": "9f2c4e1a7b3d5e60",
  "file": "onboarding-handbook.md",
  "kind": "markdown",
  "group": "documents",
  "strategy": "heading",
  "applied_strategy": "heading",          // "recursive" when the file lacks the structure (no headings, not paged, no tables)
  "size": 256,
  "overlap": 0,
  "recommended": true,
  "strategies": ["heading", "page", "recursive", "fixed"],
  "offsets": "utf-16",                    // start/end are UTF-16 code units: text.slice(start, end) in JavaScript
  "text": "Service Desk Onboarding Handbook\n\nWelcome to ...",
  "blocks": [ { "type": "heading", "start": 0, "end": 32, "level": 1, "page": null } ],
  "chunks": [ {
      "index": 0, "start": 0, "end": 655,
      "tokens": 120,                      // includes extra_tokens
      "extra_tokens": 0,                  // e.g. a table header repeated on top of a row group
      "issues": [ { "kind": "tiny", "detail": "smaller than a quarter of the target size" } ],
      "boundaries": { "start": "clean", "end": "clean" }   // clean, sentence, table_row or code
  } ],
  "metrics": { "...": "a SimulationResult for this file alone, histogram included" }
}
```

`text` is the canonical text ragcompass chunks: blocks joined by a blank line, tables as `| a | b |` lines. Chunks can
overlap each other (fixed and recursive with overlap). `issues[].kind` is one of `sentence_cut`, `table_cut`,
`orphan_heading`, `code_cut`, `tiny`.

## Benchmark

Measures retrieval quality of the recommended chunking against the next candidates by damage, with BM25, dense
embeddings (local, via fastembed) and hybrid (reciprocal rank fusion). Without the `bench` extra only BM25 runs,
`warnings` says so and the hybrid decision stays rule-based.

Queries are generated deterministically from the corpus with `seed`, in equal thirds of three kinds drawn from a
source sentence or table row: `keyphrase` (5-8 content words), `masked` (the same minus the rarest 40% of words,
codes and numbers first, which are what makes lexical matching easy) and `question` (masked words in a question
template). `lexical_overlap` is the IDF-weighted share of each source's vocabulary that its query repeats; above 0.5
`warnings` flags that the benchmark favours BM25. Synthetic queries are an approximation: `mode=llm` or a query file
measure more reliably, and the web should say so when `mode` is not `file`. The ground truth is the character span of that source, so chunkings of different
shapes are judged on the same targets: a retrieved chunk is relevant when it overlaps the span.

### `POST /api/report/{report_id}/bench`

Query: `queries=60` (number of queries, 1..500), `seed=13`, `k` (cut-off of the headline metrics, 1..10, default the
recommended top-k; curves cover 1, 3, 5, 10), `mode=template|llm` (`llm` asks a local Ollama model to write the
questions; default `template`), `dense=true` (set `false` for a fast BM25-only run), `lang` (language of
`decisions[].reason`).

Dense model: `BAAI/bge-small-en-v1.5` for English-only corpora, `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
otherwise (fastembed does not package multilingual-e5-small). Template queries reuse words of their source and favour
BM25; `warnings` says so, and `mode=llm` gives paraphrased questions.
Runs synchronously and can take a few seconds (dense models load on first use). Stores the result in the report.

### `GET /api/report/{report_id}/bench`

The last result, or 404 if no benchmark has run.

### `BenchResult`

```jsonc
{
  "k": 5,
  "seed": 13,
  "queries": 60,
  "mode": "template",                          // template, llm or file (CLI --queries-file)
  "query_kinds": { "keyphrase": 20, "masked": 20, "question": 20 },
  "lexical_overlap": { "mean": 0.298, "by_kind": { "keyphrase": 0.391, "masked": 0.216, "question": 0.288 } },
  "retrievers": ["bm25", "dense", "hybrid"],  // what could run
  "dense_model": "BAAI/bge-small-en-v1.5",    // null without the extra
  "warnings": [],
  "primary_metric": "ndcg",                    // ranking metric for the winner, at k
  "configs": [ {
      "label": "heading 256/0 · hybrid",
      "group": "documents",
      "strategy": "heading", "size": 256, "overlap": 0,
      "retriever": "hybrid",                   // bm25, dense or hybrid
      "recommended": true,                     // chunking equal to the rule-based recommendation
      "chunks": 28,
      "recall_at_k": { "mean": 0.92, "ci": [0.86, 0.97] },
      "mrr":         { "mean": 0.81, "ci": [0.73, 0.88] },
      "ndcg":        { "mean": 0.84, "ci": [0.77, 0.90] },
      "curves": { "recall": { "1": 0.70, "3": 0.88, "5": 0.92, "10": 0.97 } },
      "index_ms": 410.2,
      "query_ms": { "mean": 3.1, "p95": 5.4 }
  } ],
  "winner": { "label": "heading 256/0 · hybrid", "runner_up": "recursive 256/0 · hybrid",
              "significant": true, "margin": { "mean": 0.06, "ci": [0.02, 0.10] } },
  "decisions": [ {
      "key": "chunking.documents",             // also retrieval.retriever and retrieval.top_k
      "basis": "measured",                     // "rule-based" when the benchmark could not decide
      "rule_value": { "strategy": "heading", "size": 256, "overlap": 0 },
      "measured_value": { "strategy": "heading", "size": 256, "overlap": 0 },
      "changed": false,
      "reason": "...", "reason_i18n": { "en": "...", "es": "..." }
  } ],
  "sample_queries": [ { "id": "q001", "text": "...", "file": "hx200-maintenance-manual.pdf", "start": 120, "end": 260 } ],
  "elapsed_ms": 2310.0
}
```

Intervals are 95% percentile bootstrap intervals over queries (paired across configs for `winner.margin`), with the
same `seed`. `recall_at_k` is span recall: the share of the source span covered by the top-k chunks. `ndcg` uses
graded gains, the share of the span each chunk covers. `mrr` is the reciprocal rank of the first overlapping chunk.
`sample_queries[].start/end` are UTF-16 offsets into the `text` of that file in the chunk explorer.

## Export

### `GET /api/report/{report_id}/export`

Query: `target=yaml|langchain|llamaindex|haystack` (required). Returns `text/plain; charset=utf-8` with a
`Content-Disposition` file name (`ragcompass.yaml`, `ragcompass_langchain.py`, ...). Python targets are snippets
ready to paste: splitter with the recommended size and overlap, retriever, top-k and hybrid search. Measured values
replace rule-based ones once a benchmark has run.

## Projection

### `GET /api/report/{report_id}/projection`

2D map of the chunk embeddings for one chunking, for plotting. Uses the same local embedding model as the benchmark
and a PCA with numpy (no UMAP), so the same input always gives the same picture. Returns 501 when the `bench` extra
is not installed.

| Query | Default | Notes |
|---|---|---|
| `group` | `documents` if present, else the largest group | `documents`, `tables` or `code` |
| `strategy`, `size`, `overlap` | recommended for the group | as in the chunk explorer |
| `queries` | `true` | project the benchmark queries too (drawn with `seed`) |
| `seed` | `13` | |

```jsonc
{
  "model": "BAAI/bge-small-en-v1.5",
  "group": "documents", "strategy": "heading", "size": 256, "overlap": 0,
  "explained_variance": [0.21, 0.12],           // share of variance on x and y
  "points": [ {
      "id": 0,                                  // position in this array
      "file": "onboarding-handbook.md",
      "chunk_index": 0,                         // index in /chunks for that file and configuration
      "x": -0.41, "y": 0.12,                    // scaled to [-1, 1]
      "tokens": 120,
      "preview": "Service Desk Onboarding Handbook. Welcome to the service desk..."   // first 160 characters
  } ],
  "queries": [ { "id": "q001", "text": "...", "x": 0.3, "y": -0.2, "neighbors": [4, 9, 2] } ]   // point ids, nearest first, top 5
}
```

At most 2,000 points are returned; larger corpora are sampled deterministically with `seed`.

## Query files (CLI)

`ragcompass bench <path> --queries-file queries.jsonl` replaces the generated queries with your own. JSON list or
JSON Lines; each entry:

```json
{"id": "u1", "text": "how do I open the back cover?", "answer": "Remove the four screws of the rear grille with a T10 driver.", "file": "hx200-maintenance-manual.pdf"}
```

`text` is the query, `answer` a passage copied from the document (located with whitespace normalised; it becomes the
ground-truth span), `file` optional (otherwise every file is searched), `id` optional.
