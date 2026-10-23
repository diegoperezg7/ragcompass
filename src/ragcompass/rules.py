"""Deterministic rule engine: profiles and simulations in, reasoned settings out.

Every threshold lives here with the reason it exists, so a recommendation can
always be traced back to a number measured on the corpus.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from ragcompass.models import (
    BlockType,
    DocKind,
    DocProfile,
    EmbeddingCost,
    IndexEstimate,
    Recommendation,
    SimulationResult,
)
from ragcompass.simulate import (
    PREFERENCE,
    SIZES,
    STRUCTURE_SHARE,
    Doc,
    group_of,
    has_headings,
    percentile,
    token_share,
)

# Chunking
DEFAULT_PROSE_SIZE = 512  # common retriever sweet spot: one idea per chunk, enough context
DENSE_ID_PROSE_SIZE = 256  # lookup-style text: small chunks keep one fact per vector
CODE_SIZE = 512  # fits a typical function with its signature and docstring
ROWS_PER_TABLE_CHUNK = 8  # enough rows to answer range questions without mixing far records
OVERLAP_LOW_CUTS = 15.0  # % of sentence cuts below which 10% overlap is enough

# Hybrid search: dense embeddings split codes like "SKU-4471-B" into sub-word pieces
# and match them poorly; BM25 matches them exactly.
HYBRID_CODES_PER_1K = 3.0
HYBRID_IDS_PER_1K = 25.0
DATE_FIELD_PER_1K = 2.0

# Retrieval
CONTEXT_BUDGET = 3000  # tokens of retrieved context handed to the generator
MIN_TOP_K, MAX_TOP_K = 3, 10
RERANK_MIN_VECTORS = 1000  # below this, a dense top-k is usually already precise
RERANK_CANDIDATES = 4  # retrieve this many times top-k for the reranker

# Index
HNSW_M = 16  # neighbours per node; layer-0 links are 2*M ids of 4 bytes each
INT8_THRESHOLD_BYTES = 1 << 30  # quantize once the float32 index passes 1 GiB
DIMENSIONS = (384, 768, 1024, 1536, 3072)
SCANNED_PAGE_TOKENS = 450  # typical OCR yield of a dense A4 page, used only for scans

EMBEDDING_PRICES = {  # USD per million tokens, reference list prices
    "local (Ollama: nomic-embed-text, bge-m3)": 0.0,
    "openai text-embedding-3-small": 0.02,
    "openai text-embedding-3-large": 0.13,
}

PARSERS = {
    DocKind.PDF_TEXT: "pymupdf text layer",
    DocKind.PDF_SCANNED: "OCR (Tesseract via OCRmyPDF)",
    DocKind.PDF_MIXED: "pymupdf text layer + per-page OCR fallback",
    DocKind.DOCX: "python-docx (heading styles, tables in body order)",
    DocKind.MARKDOWN: "markdown parser keeping heading hierarchy",
    DocKind.HTML: "BeautifulSoup with nav, footer and scripts stripped",
    DocKind.CSV: "row serializer (header + row per record)",
    DocKind.XLSX: "openpyxl row serializer, one table per sheet",
    DocKind.CODE: "language-aware splitter on class/function boundaries",
    DocKind.TEXT: "plain text, paragraphs on blank lines",
    DocKind.IMAGE: "vision-language model captions (e.g. qwen2.5-vl via Ollama)",
}
FIGURES_PER_PAGE_VLM = 0.5  # above this, figures carry enough content to caption them


@dataclass
class Plan:
    recommendations: list[Recommendation] = field(default_factory=list)
    index: list[IndexEstimate] = field(default_factory=list)
    costs: list[EmbeddingCost] = field(default_factory=list)
    config: dict = field(default_factory=dict)

    def add(self, key: str, value, reason: str, **evidence) -> None:
        self.recommendations.append(Recommendation(key=key, value=value, reason=reason, evidence=evidence))


def n(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def smallest_size_at_least(tokens: float) -> int:
    for size in SIZES:
        if size >= tokens:
            return size
    return SIZES[-1]


def section_tokens(docs: list[Doc]) -> list[int]:
    out = []
    for doc in docs:
        layout = doc.layout
        starts = [s.start for s in layout.spans if layout.blocks[s.block].type == BlockType.HEADING]
        if not starts:
            continue
        bounds = starts + [len(layout.text)]
        out.extend(layout.tokens.count(a, b) for a, b in zip(bounds, bounds[1:], strict=False))
    return out


def row_tokens(docs: list[Doc]) -> list[int]:
    out = []
    for doc in docs:
        layout = doc.layout
        for span in layout.spans:
            if layout.blocks[span.block].type != BlockType.TABLE:
                continue
            position = span.start
            for line in layout.text[span.start : span.end].split("\n"):
                out.append(layout.tokens.count(position, position + len(line)))
                position += len(line) + 1
    return out


def _corpus_density(profiles: list[DocProfile]) -> tuple[float, float, float]:
    tokens = sum(p.tokens for p in profiles)
    if not tokens:
        return 0.0, 0.0, 0.0
    ids = sum(p.identifiers.codes + p.identifiers.dates + p.identifiers.numbers for p in profiles)
    codes = sum(p.identifiers.codes for p in profiles)
    dates = sum(p.identifiers.dates for p in profiles)
    scale = 1000 / tokens
    return round(ids * scale, 1), round(codes * scale, 1), round(dates * scale, 1)


def _languages(profiles: list[DocProfile]) -> dict[str, int]:
    tokens: Counter[str] = Counter()
    for p in profiles:
        if p.language:
            tokens[p.language] += p.tokens
    return dict(tokens.most_common())


def _parser_rules(plan: Plan, profiles: list[DocProfile]) -> dict[str, str]:
    parsing = {}
    by_kind: dict[DocKind, list[DocProfile]] = {}
    for p in profiles:
        if p.kind != DocKind.UNSUPPORTED and not p.error:
            by_kind.setdefault(p.kind, []).append(p)
    for kind, docs in by_kind.items():
        parser = PARSERS[kind]
        pages = sum(p.pages or 0 for p in docs)
        names = len(docs)
        if kind == DocKind.PDF_TEXT:
            per_page = round(sum(p.chars for p in docs) / pages) if pages else 0
            reason = (
                f"{n(pages, 'page')} with a usable text layer (avg {per_page} chars/page); no OCR needed."
            )
        elif kind in (DocKind.PDF_SCANNED, DocKind.PDF_MIXED):
            scanned = sum(p.scanned_pages for p in docs)
            reason = (
                f"{scanned} of {n(pages, 'page')} {'has' if scanned == 1 else 'have'} under 25 characters of text "
                "and a page-wide image: "
                "scans need OCR before chunking."
            )
        elif kind == DocKind.IMAGE:
            reason = (
                f"{n(names, 'image')} with no text layer; a VLM caption or OCR is the only way to index them."
            )
        elif kind in (DocKind.CSV, DocKind.XLSX):
            rows = sum(p.table_rows for p in docs)
            reason = f"{rows} data rows; serializing each row with its header keeps values attached to column names."
        elif kind == DocKind.CODE:
            reason = f"{n(names, 'source file')}; splitting on definitions keeps functions whole."
        else:
            headings = sum(p.headings for p in docs)
            tables = sum(p.tables for p in docs)
            reason = (
                f"{n(names, 'file')} with {n(headings, 'heading')} and {n(tables, 'table')}; "
                "the parser preserves both."
            )
        figures = sum(p.images for p in docs)
        if pages and kind.value.startswith("pdf") and figures / pages >= FIGURES_PER_PAGE_VLM:
            parser += " + VLM captions for figures"
            reason += f" {figures} figures over {pages} pages is enough to caption them."
        parsing[kind.value] = parser
        plan.add(f"parser.{kind.value}", parser, reason, files=names, pages=pages or None)
    return parsing


def _overlap_for(results: dict[tuple[str, int, int], SimulationResult], strategy: str, size: int) -> int:
    if strategy not in ("fixed", "recursive"):
        return 0
    base = results[(strategy, size, 0)]
    if base.sentence_cut_pct == 0:
        return 0
    return int(size * (0.1 if base.sentence_cut_pct < OVERLAP_LOW_CUTS else 0.2))


def _chunking_rules(
    plan: Plan, group: str, docs: list[Doc], sims: list[SimulationResult], density: tuple[float, float, float]
) -> SimulationResult:
    results = {(s.strategy, s.size, s.overlap): s for s in sims if s.group == group}
    strategies = sorted({s.strategy for s in sims if s.group == group}, key=PREFERENCE.index)

    if group == "tables":
        rows = row_tokens(docs)
        median_row = percentile(rows, 50)
        size = smallest_size_at_least(median_row * (ROWS_PER_TABLE_CHUNK + 1))
        size_reason = (
            f"median row is {median_row} tokens, so {size} fits the header plus {ROWS_PER_TABLE_CHUNK} rows"
        )
    elif group == "code":
        size = CODE_SIZE
        size_reason = f"{CODE_SIZE} tokens fits a typical function with its signature and docstring"
    else:
        structured = token_share(docs, has_headings)
        sections = section_tokens(docs)
        if structured >= STRUCTURE_SHARE and sections:
            median = percentile(sections, 50)
            size = smallest_size_at_least(median)
            share = round(100 * structured)
            size_reason = (
                f"{share}% of the text sits under headings and the median section is {median} tokens"
            )
        elif density[1] >= HYBRID_CODES_PER_1K:
            size = DENSE_ID_PROSE_SIZE
            size_reason = f"{density[1]} codes per 1k tokens: small chunks keep one fact per vector"
        else:
            size = DEFAULT_PROSE_SIZE
            size_reason = "unstructured prose with few identifiers; 512 is a balanced default"

    candidates = [results[(s, size, _overlap_for(results, s, size))] for s in strategies]
    best = min(candidates, key=lambda r: (r.damage, PREFERENCE.index(r.strategy)))
    fixed = results[("fixed", size, 0)]
    others = ", ".join(f"{c.strategy} {c.damage}" for c in candidates if c is not best)
    reason = (
        f"{size_reason}. At {size} tokens, {best.strategy} has the lowest damage score "
        f"({best.damage}: {best.sentence_cut_pct}% sentence cuts, {best.table_cut_pct}% table cuts, "
        f"{best.orphan_heading_pct}% orphan headings, {best.tiny_pct}% tiny chunks) against {others}."
    )
    if best.overlap:
        no_overlap = results[(best.strategy, size, 0)]
        reason += (
            f" Overlap {best.overlap} tokens because {no_overlap.sentence_cut_pct}% of chunks cut a "
            f"sentence without it (+{best.overhead_pct}% tokens embedded)."
        )
    plan.add(
        f"chunking.{group}",
        {"strategy": best.strategy, "size": size, "overlap": best.overlap},
        reason,
        chunks=best.chunks,
        damage=best.damage,
        fixed_baseline_damage=fixed.damage,
    )
    return best


def recommend(profiles: list[DocProfile], docs: list[Doc], sims: list[SimulationResult]) -> Plan:
    plan = Plan()
    usable = [p for p in profiles if not p.error and p.kind != DocKind.UNSUPPORTED]
    density = _corpus_density(usable)
    languages = _languages(usable)
    text_tokens = sum(languages.values())

    parsing = _parser_rules(plan, usable)

    groups: dict[str, list[Doc]] = {}
    for doc in docs:
        group = group_of(doc.kind)
        if group and len(doc.layout.tokens):
            groups.setdefault(group, []).append(doc)
    chosen = {
        group: _chunking_rules(plan, group, members, sims, density) for group, members in groups.items()
    }

    # Vectors: simulated chunks, plus one caption per image and an estimate for scanned pages.
    simulated = sum(r.chunks for r in chosen.values())
    images = sum(p.images for p in usable)
    scanned = sum(p.scanned_pages for p in usable)
    doc_size = chosen["documents"].size if "documents" in chosen else DEFAULT_PROSE_SIZE
    scan_vectors = scanned * math.ceil(SCANNED_PAGE_TOKENS / doc_size)
    vectors = simulated + images + scan_vectors
    embedded_tokens = sum(r.total_tokens for r in chosen.values()) + scanned * SCANNED_PAGE_TOKENS
    parts = [f"{simulated} chunks measured by the simulation"]
    if images:
        parts.append(f"{images} image captions")
    if scan_vectors:
        parts.append(
            f"~{scan_vectors} estimated for {n(scanned, 'scanned page')} at {SCANNED_PAGE_TOKENS} tokens/page after OCR"
        )
    plan.add(
        "vectors",
        vectors,
        " + ".join(parts) + ".",
        simulated=simulated,
        images=images,
        scanned_estimate=scan_vectors,
    )

    # Embedding dimension and quantization.
    multilingual = sum(1 for t in languages.values() if text_tokens and t / text_tokens >= 0.1) > 1
    main_language = next(iter(languages), None)
    if multilingual or (main_language and main_language != "en"):
        dimension, models = 1024, ["bge-m3", "multilingual-e5-large"]
        mix = ", ".join(f"{lang} {round(100 * t / text_tokens)}%" for lang, t in languages.items())
        dim_reason = f"text is not English-only ({mix}); multilingual models at 1024 dims handle it."
    else:
        dimension, models = 768, ["nomic-embed-text", "bge-base-en-v1.5"]
        dim_reason = "English-only text; 768-dim models give strong recall at half the storage of 1536."
    plan.add("embedding.dimension", dimension, dim_reason, models=models, languages=languages)

    for dim in DIMENSIONS:
        plan.index.append(
            IndexEstimate(
                dimension=dim,
                vectors=vectors,
                float32_bytes=vectors * dim * 4,
                int8_bytes=vectors * dim,
                hnsw_overhead_bytes=vectors * HNSW_M * 2 * 4,
            )
        )
    chosen_index = next(i for i in plan.index if i.dimension == dimension)
    float32_total = chosen_index.float32_bytes + chosen_index.hnsw_overhead_bytes
    if float32_total > INT8_THRESHOLD_BYTES:
        quantization = "int8"
        q_reason = f"float32 index at {dimension} dims is {human_bytes(float32_total)}; int8 cuts vectors 4x."
    else:
        quantization = "float32"
        q_reason = (
            f"float32 index at {dimension} dims is {human_bytes(float32_total)}, well under 1 GiB; "
            "quantization would trade recall for memory you do not need to save."
        )
    plan.add("embedding.quantization", quantization, q_reason, index_bytes=float32_total)

    for model, price in EMBEDDING_PRICES.items():
        plan.costs.append(
            EmbeddingCost(
                model=model,
                usd_per_million=price,
                tokens=embedded_tokens,
                usd=round(embedded_tokens * price / 1_000_000, 4),
            )
        )
    priciest = plan.costs[-1]
    plan.add(
        "embedding.cost",
        f"${priciest.usd:.4f} max",
        f"{embedded_tokens:,} tokens to embed (overlap and repeated headers included); "
        f"local models cost nothing, the largest hosted model costs ${priciest.usd:.4f} per full index.",
        tokens=embedded_tokens,
    )

    # Retrieval.
    hybrid = density[1] >= HYBRID_CODES_PER_1K or density[0] >= HYBRID_IDS_PER_1K
    if hybrid:
        h_reason = (
            f"{density[1]} codes and {density[0]} identifiers per 1k tokens: exact tokens like SKUs "
            "and dates are matched far better by BM25 than by dense vectors."
        )
    else:
        h_reason = f"only {density[1]} codes and {density[0]} identifiers per 1k tokens; dense retrieval alone is enough."
    plan.add("retrieval.hybrid_bm25", hybrid, h_reason, ids_per_1k=density[0], codes_per_1k=density[1])

    top_k = max(MIN_TOP_K, min(MAX_TOP_K, round(CONTEXT_BUDGET / doc_size)))
    rerank = vectors >= RERANK_MIN_VECTORS or len(groups) > 1
    candidates = top_k * RERANK_CANDIDATES if rerank else top_k
    plan.add(
        "retrieval.top_k",
        {"candidates": candidates, "final": top_k},
        f"a {CONTEXT_BUDGET}-token context budget over {doc_size}-token chunks gives {top_k} chunks"
        + (f"; retrieve {candidates} so the reranker has room to reorder." if rerank else "."),
    )
    if rerank:
        why = []
        if vectors >= RERANK_MIN_VECTORS:
            why.append(f"{vectors} vectors is past the {RERANK_MIN_VECTORS} where dense top-k gets noisy")
        if len(groups) > 1:
            why.append(f"{len(groups)} content types ({', '.join(groups)}) score on different scales")
        r_reason = "; ".join(why) + ". A cross-encoder puts them on one relevance scale."
    else:
        r_reason = (
            f"{vectors} vectors of one content type; dense top-{top_k} is precise enough without a reranker."
        )
    plan.add("retrieval.reranker", "bge-reranker-v2-m3" if rerank else False, r_reason)

    # Metadata.
    fields = {"source": "every chunk must cite its file", "chunk_index": "lets you expand to neighbours"}
    if any(p.pages for p in usable):
        fields["page"] = "paged sources: citations point to a page"
    if any(r.strategy == "heading" for r in chosen.values()) or any(p.headings for p in usable):
        fields["heading_path"] = "headings give the chunk its context and a filter"
    if "tables" in groups:
        fields["sheet"] = "workbooks: keep which sheet a row came from"
        fields["row_range"] = "tables: cite the exact rows"
    if multilingual:
        fields["language"] = "mixed languages: filter or route by language"
    if density[2] >= DATE_FIELD_PER_1K:
        fields["dates"] = f"{density[2]} dates per 1k tokens: extract them for time filters"
    if len(groups) > 1 or images:
        fields["doc_kind"] = "mixed formats: filter tables, prose and captions separately"
    plan.add("metadata", list(fields), "; ".join(f"{k}: {v}" for k, v in fields.items()) + ".")

    plan.config = {
        "parsing": parsing,
        "chunking": {
            group: {"strategy": r.strategy, "size": r.size, "overlap": r.overlap}
            for group, r in chosen.items()
        },
        "embedding": {
            "dimension": dimension,
            "models": models,
            "quantization": quantization,
            "vectors": vectors,
            "index_bytes": float32_total
            if quantization == "float32"
            else chosen_index.int8_bytes + chosen_index.hnsw_overhead_bytes,
        },
        "retrieval": {
            "top_k": top_k,
            "candidates": candidates,
            "hybrid_bm25": hybrid,
            "reranker": "bge-reranker-v2-m3" if rerank else None,
        },
        "metadata": list(fields),
    }
    return plan


def human_bytes(value: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"
