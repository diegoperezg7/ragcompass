# ragcompass report: corpus

9 of 9 files analysed, 4,624 tokens (cl100k_base), 4 pages, languages: en, es.

## Recommendations

| Setting | Value | Why |
|---|---|---|
| parser.html | BeautifulSoup with nav, footer and scripts stripped | 1 file with 6 headings and 0 tables; the parser preserves both. |
| parser.pdf_text | pymupdf text layer | 3 pages with a usable text layer (avg 1701 chars/page); no OCR needed. |
| parser.markdown | markdown parser keeping heading hierarchy | 1 file with 6 headings and 1 table; the parser preserves both. |
| parser.docx | python-docx (heading styles, tables in body order) | 1 file with 5 headings and 1 table; the parser preserves both. |
| parser.csv | row serializer (header + row per record) | 40 data rows; serializing each row with its header keeps values attached to column names. |
| parser.pdf_scanned | OCR (Tesseract via OCRmyPDF) | 1 of 1 page has under 25 characters of text and a page-wide image: scans need OCR before chunking. |
| parser.code | language-aware splitter on class/function boundaries | 1 source file; splitting on definitions keeps functions whole. |
| parser.xlsx | openpyxl row serializer, one table per sheet | 14 data rows; serializing each row with its header keeps values attached to column names. |
| parser.image | vision-language model captions (e.g. qwen2.5-vl via Ollama) | 1 image with no text layer; a VLM caption or OCR is the only way to index them. |
| chunking.documents | strategy heading, size 256, overlap 0 | 100% of the text sits under headings and the median section is 75 tokens. At 256 tokens, heading has the lowest damage score (13.3: 0.0% sentence cuts, 0.0% table cuts, 0.0% orphan headings, 13.3% tiny chunks) against recursive 25.0, fixed 146.2. |
| chunking.tables | strategy row, size 512, overlap 0 | median row is 35 tokens, so 512 fits the header plus 8 rows. At 512 tokens, row has the lowest damage score (0.0: 0.0% sentence cuts, 0.0% table cuts, 0.0% orphan headings, 0.0% tiny chunks) against recursive 150.0, fixed 225.0. |
| chunking.code | strategy recursive, size 512, overlap 0 | 512 tokens fits a typical function with its signature and docstring. At 512 tokens, recursive has the lowest damage score (0.0: 0.0% sentence cuts, 0.0% table cuts, 0.0% orphan headings, 0.0% tiny chunks) against fixed 0.0. |
| vectors | 28 | 21 chunks measured by the simulation + 5 image captions + ~2 estimated for 1 scanned page at 450 tokens/page after OCR. |
| embedding.dimension | 1,024 | text is not English-only (en 81%, es 19%); multilingual models at 1024 dims handle it. |
| embedding.quantization | float32 | float32 index at 1024 dims is 115.5 KiB, well under 1 GiB; quantization would trade recall for memory you do not need to save. |
| embedding.cost | $0.0007 max | 5,106 tokens to embed (overlap and repeated headers included); local models cost nothing, the largest hosted model costs $0.0007 per full index. |
| retrieval.hybrid_bm25 | yes | 21.4 codes and 80.0 identifiers per 1k tokens: exact tokens like SKUs and dates are matched far better by BM25 than by dense vectors. |
| retrieval.top_k | candidates 40, final 10 | a 3000-token context budget over 256-token chunks gives 10 chunks; retrieve 40 so the reranker has room to reorder. |
| retrieval.reranker | bge-reranker-v2-m3 | 3 content types (documents, tables, code) score on different scales. A cross-encoder puts them on one relevance scale. |
| metadata | source, chunk_index, page, heading_path, sheet, row_range, language, dates, doc_kind | source: every chunk must cite its file; chunk_index: lets you expand to neighbours; page: paged sources: citations point to a page; heading_path: headings give the chunk its context and a filter; sheet: workbooks: keep which sheet a row came from; row_range: tables: cite the exact rows; language: mixed languages: filter or route by language; dates: 9.1 dates per 1k tokens: extract them for time filters; doc_kind: mixed formats: filter tables, prose and captions separately. |

## Documents

| File | Kind | Pages | Tokens | Lang | Headings | Tables | Lists | Images | IDs/1k |
|---|---|---|---|---|---|---|---|---|---|
| hx200-faq.html | html |  | 219 | en | 6 | 0 | 0 | 2 | 41.1 |
| hx200-maintenance-manual.pdf | pdf_text | 3 | 1210 | en | 8 | 2 | 8 | 1 | 53.7 |
| onboarding-handbook.md | markdown |  | 622 | en | 6 | 1 | 7 | 0 | 12.9 |
| politica-devoluciones.docx | docx |  | 479 | es | 5 | 1 | 4 | 1 | 10.4 |
| product-catalog.csv | csv |  | 1458 |  | 0 | 1 | 0 | 0 | 142.0 |
| scanned-invoice.pdf | pdf_scanned | 1 | 0 |  | 0 | 0 | 0 | 0 | 0.0 |
| ticket_export.py | code |  | 291 |  | 0 | 0 | 0 | 0 | 20.6 |
| warehouse-stock.xlsx | xlsx |  | 345 |  | 2 | 2 | 0 | 0 | 202.9 |
| wiring-diagram.png | image |  | 0 |  | 0 | 0 | 0 | 1 | 0.0 |

## Chunking simulation (recommended size)

| Group | Strategy | Size | Overlap | Chunks | p50 | p95 | Sentence cuts | Table cuts | Orphan headings | Tiny | Damage |
|---|---|---|---|---|---|---|---|---|---|---|---|
| documents | heading | 256 | 0 | 15 | 197 | 243 | 0.0% | 0.0% | 0.0% | 13.3% | 13.3 |
| documents | recursive | 256 | 0 | 12 | 209 | 244 | 0.0% | 0.0% | 25.0% | 0.0% | 25.0 |
| documents | recursive | 256 | 25 | 12 | 217 | 251 | 0.0% | 0.0% | 25.0% | 0.0% | 25.0 |
| documents | recursive | 256 | 51 | 13 | 217 | 244 | 0.0% | 0.0% | 30.8% | 0.0% | 30.8 |
| documents | fixed | 256 | 51 | 13 | 256 | 256 | 76.9% | 23.1% | 0.0% | 0.0% | 146.2 |
| documents | fixed | 256 | 25 | 12 | 256 | 256 | 83.3% | 25.0% | 0.0% | 8.3% | 166.6 |
| documents | fixed | 256 | 0 | 11 | 256 | 256 | 81.8% | 36.4% | 0.0% | 0.0% | 191.0 |
| tables | row | 512 | 0 | 5 | 490 | 504 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0 |
| tables | recursive | 512 | 0 | 4 | 480 | 490 | 0.0% | 50.0% | 0.0% | 0.0% | 150.0 |
| tables | recursive | 512 | 102 | 5 | 479 | 490 | 0.0% | 60.0% | 0.0% | 0.0% | 180.0 |
| tables | recursive | 512 | 51 | 5 | 482 | 490 | 0.0% | 60.0% | 0.0% | 20.0% | 200.0 |
| tables | fixed | 512 | 0 | 4 | 434 | 512 | 0.0% | 75.0% | 0.0% | 0.0% | 225.0 |
| tables | fixed | 512 | 102 | 5 | 512 | 512 | 0.0% | 80.0% | 0.0% | 0.0% | 240.0 |
| tables | fixed | 512 | 51 | 5 | 512 | 512 | 0.0% | 80.0% | 0.0% | 20.0% | 260.0 |
| code | fixed | 512 | 0 | 1 | 291 | 291 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0 |
| code | fixed | 512 | 51 | 1 | 291 | 291 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0 |
| code | fixed | 512 | 102 | 1 | 291 | 291 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0 |
| code | recursive | 512 | 0 | 1 | 291 | 291 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0 |
| code | recursive | 512 | 51 | 1 | 291 | 291 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0 |
| code | recursive | 512 | 102 | 1 | 291 | 291 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0 |

## Index size

| Dimension | Vectors | float32 | int8 | HNSW graph |
|---|---|---|---|---|
| 384 | 28 | 42.0 KiB | 10.5 KiB | 3.5 KiB |
| 768 | 28 | 84.0 KiB | 21.0 KiB | 3.5 KiB |
| 1024 | 28 | 112.0 KiB | 28.0 KiB | 3.5 KiB |
| 1536 | 28 | 168.0 KiB | 42.0 KiB | 3.5 KiB |
| 3072 | 28 | 336.0 KiB | 84.0 KiB | 3.5 KiB |

## Embedding cost

| Model | USD / 1M tokens | Tokens | USD |
|---|---|---|---|
| local (Ollama: nomic-embed-text, bge-m3) | 0.0 | 5,106 | 0.0000 |
| openai text-embedding-3-small | 0.02 | 5,106 | 0.0001 |
| openai text-embedding-3-large | 0.13 | 5,106 | 0.0007 |
