"""Reason templates and report labels in English and Spanish.

Rules emit reasons as message ids with parameters; this module renders them. Templates use
``str.format`` fields plus two extensions handled by :class:`Formatter`:

- ``{n:file|files}`` picks the singular when ``n == 1`` and the plural otherwise;
- numbers are written with the separators of the language (``12,345.5`` / ``12.345,5``), with no
  group separator below 10,000;
- ``{n:bytes}`` writes a byte count as ``1.2 MiB``;
- a list of pairs such as ``[["fixed", 191.0], ...]`` is written as ``fixed 191.0, ...``.

Parameters stay plain JSON values, so a report can be rendered again in any language.
"""

from __future__ import annotations

import string
from typing import Any

LANGUAGES = ("en", "es")

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # Parsing
        "parser.pdf_text": "{pages} {pages:page|pages} with a usable text layer (avg {per_page} chars/page); no OCR needed.",
        "parser.scanned": "{scanned} of {pages} {pages:page|pages} {scanned:has|have} no usable text layer under a page-wide image: scans need OCR before chunking.",
        "parser.image": "{files} {files:image|images} with no text layer; a VLM caption or OCR is the only way to index them.",
        "parser.tabular": "{rows} data {rows:row|rows}; serializing each row with its header keeps values attached to column names.",
        "parser.code": "{files} source {files:file|files}; splitting on definitions keeps functions whole.",
        "parser.structured": "{files} {files:file|files} with {headings} {headings:heading|headings} and {tables} {tables:table|tables}; the parser preserves both.",
        "parser.figures": "{figures} {figures:figure|figures} over {pages} {pages:page|pages} is enough to caption them.",
        # Chunking
        "chunking.size.tables": "The median row is {row} tokens, so {size} fits the header plus {rows} rows.",
        "chunking.size.code": "{size} tokens fits a typical function with its signature and docstring.",
        "chunking.size.structured": "{share}% of the text sits under headings and the median section is {median} tokens.",
        "chunking.size.dense_ids": "{codes} codes per 1k tokens: small chunks keep one fact per vector.",
        "chunking.size.default": "Unstructured prose with few identifiers; 512 is a balanced default.",
        "chunking.pick": "At {size} tokens, {strategy} has the lowest damage score ({damage}: {sentence}% sentence cuts, {table}% table cuts, {orphan}% orphan headings, {code}% code cuts, {tiny}% tiny chunks) against {others}.",
        "chunking.overlap": "Overlap of {overlap} tokens because {cuts}% of chunks cut a sentence without it (+{overhead}% tokens embedded).",
        # Vectors
        "vectors.simulated": "{chunks} {chunks:chunk|chunks} measured by the simulation.",
        "vectors.captions": "Plus {images} image {images:caption|captions} of ~{tokens} tokens each.",
        "vectors.scans": "Plus ~{vectors} estimated for {pages} scanned {pages:page|pages} at {tokens} tokens per page after OCR.",
        # Embeddings
        "embedding.dimension.undecided": "Insufficient evidence: no language could be detected in {tokens} tokens of text; decide after OCR.",
        "embedding.dimension.multilingual": "The text is not English-only ({mix}); multilingual models at 1024 dims handle it.",
        "embedding.dimension.english": "English-only text; 768-dim models give strong recall at half the storage of 1536.",
        "embedding.quantization.undecided": "Insufficient evidence: the dimension is not decided yet; decide after OCR.",
        "embedding.quantization.int8": "The float32 index at {dimension} dims is {size:bytes}; int8 cuts the vectors 4x.",
        "embedding.quantization.float32": "The float32 index at {dimension} dims is {size:bytes}, well under 1 GiB; quantization would trade recall for memory you do not need to save.",
        "embedding.cost": "{tokens} tokens to embed (overlap, repeated headers and image captions included); local models cost nothing, the largest hosted model costs ${usd:.4f} per full index.",
        # Retrieval
        "retrieval.hybrid.undecided": "Insufficient evidence: there is no text to measure identifiers in; decide after OCR.",
        "retrieval.hybrid.yes": "{codes} codes and {ids} identifiers per 1k tokens: exact tokens like SKUs and dates are matched far better by BM25 than by dense vectors.",
        "retrieval.hybrid.no": "Only {codes} codes and {ids} identifiers per 1k tokens; dense retrieval alone is enough.",
        "retrieval.top_k": "A {budget}-token context budget over chunks of up to {largest} tokens fits {k}.",
        "retrieval.top_k.all": "That is every vector in the index.",
        "retrieval.top_k.rerank": "Retrieve {candidates} so the reranker has room to reorder.",
        "retrieval.reranker.yes": "{vectors} vectors is past {threshold}: the first page of dense results fills with near-miss neighbours, and a cross-encoder over {candidates} candidates restores precision.",
        "retrieval.reranker.no": "{vectors} {vectors:vector is|vectors is} below {threshold}: a top-{k} from the index is precise enough, and a reranker would add one model call per candidate. Add one if evaluation shows misses.",
        # Metadata
        "metadata.source": "source: every chunk must cite its file.",
        "metadata.chunk_index": "chunk_index: lets you expand to neighbouring chunks.",
        "metadata.page": "page: citations point to a page.",
        "metadata.heading_path": "heading_path: headings give the chunk its context and a filter.",
        "metadata.sheet": "sheet: keep which sheet a row came from.",
        "metadata.row_range": "row_range: cite the exact rows.",
        "metadata.language": "language: mixed languages, filter or route by language.",
        "metadata.dates": "dates: {dates} dates per 1k tokens, extract them for time filters.",
        "metadata.doc_kind": "doc_kind: mixed formats, filter tables, prose and captions separately.",
        # Benchmark
        "bench.chunking.confirmed": "Benchmark ({queries} queries): {config} scores nDCG@{k} {score} [{low}, {high}]; no other candidate beats it by a significant margin.",
        "bench.chunking.changed": "Benchmark ({queries} queries): {winner} scores nDCG@{k} {score} against {score_rule} for the rule-based {rule}; the gap {gap} [{low}, {high}] excludes zero, so the measurement wins.",
        "bench.hybrid.better": "Benchmark: adding BM25 to dense retrieval lifts nDCG@{k} from {dense} to {hybrid}; the gap {gap} [{low}, {high}] excludes zero. BM25 alone scores {bm25}.",
        "bench.hybrid.worse": "Benchmark: dense retrieval alone scores nDCG@{k} {dense} against {hybrid} with BM25 fused in (gap {gap} [{low}, {high}]), so hybrid search does not pay off here.",
        "bench.hybrid.tie": "Benchmark: hybrid ({hybrid}) and dense alone ({dense}) are within noise on nDCG@{k} (gap interval [{low}, {high}] includes zero); the rule decides. BM25 alone scores {bm25}.",
        "bench.hybrid.unavailable": "Not measured: dense embeddings need the bench extra (pip install 'ragcompass[bench]').",
        "bench.top_k.lower": "Benchmark: recall@{k} is already {recall}, {share}% of recall@10 ({recall10}), so {k} chunks are enough instead of {rule_k}.",
        "bench.top_k.confirmed": "Benchmark: it takes {k} chunks to reach {share}% of recall@10 ({recall10}); recall@{rule_k} is {rule_recall}, so the budget-based value stays.",
    },
    "es": {
        "parser.pdf_text": "{pages} {pages:página|páginas} con una capa de texto utilizable (media de {per_page} caracteres por página); no hace falta OCR.",
        "parser.scanned": "{scanned} de {pages} {pages:página|páginas} no {scanned:tiene|tienen} una capa de texto utilizable bajo una imagen que ocupa la página: son escaneos y necesitan OCR antes del chunking.",
        "parser.image": "{files} {files:imagen|imágenes} sin capa de texto; un caption con un modelo de visión o el OCR son la única forma de indexarlas.",
        "parser.tabular": "{rows} {rows:fila|filas} de datos; serializar cada fila con su cabecera mantiene los valores unidos a los nombres de columna.",
        "parser.code": "{files} {files:fichero|ficheros} de código; partir por definiciones mantiene las funciones enteras.",
        "parser.structured": "{files} {files:fichero|ficheros} con {headings} {headings:encabezado|encabezados} y {tables} {tables:tabla|tablas}; el parser conserva ambos.",
        "parser.figures": "{figures} {figures:figura|figuras} en {pages} {pages:página|páginas} justifican generarles captions.",
        "chunking.size.tables": "La fila mediana tiene {row} tokens, así que {size} da cabida a la cabecera y {rows} filas.",
        "chunking.size.code": "{size} tokens dan cabida a una función típica con su firma y su docstring.",
        "chunking.size.structured": "El {share}% del texto está bajo encabezados y la sección mediana tiene {median} tokens.",
        "chunking.size.dense_ids": "{codes} códigos por cada 1k tokens: los chunks pequeños guardan un dato por vector.",
        "chunking.size.default": "Prosa sin estructura y con pocos identificadores; 512 es un valor equilibrado.",
        "chunking.pick": "Con {size} tokens, {strategy} obtiene la menor puntuación de daño ({damage}: {sentence}% de frases cortadas, {table}% de tablas cortadas, {orphan}% de encabezados huérfanos, {code}% de código cortado, {tiny}% de chunks diminutos) frente a {others}.",
        "chunking.overlap": "Solape de {overlap} tokens porque, sin él, el {cuts}% de los chunks corta una frase (+{overhead}% de tokens a embeber).",
        "vectors.simulated": "{chunks} {chunks:chunk medido|chunks medidos} en la simulación.",
        "vectors.captions": "Más {images} {images:caption|captions} de imagen de ~{tokens} tokens cada uno.",
        "vectors.scans": "Más ~{vectors} estimados para {pages} {pages:página escaneada|páginas escaneadas} a {tokens} tokens por página tras el OCR.",
        "embedding.dimension.undecided": "Evidencia insuficiente: no se ha podido detectar el idioma en {tokens} tokens de texto; decide después del OCR.",
        "embedding.dimension.multilingual": "El texto no está solo en inglés ({mix}); los modelos multilingües de 1024 dimensiones lo cubren.",
        "embedding.dimension.english": "Texto solo en inglés; los modelos de 768 dimensiones dan buen recall con la mitad de almacenamiento que 1536.",
        "embedding.quantization.undecided": "Evidencia insuficiente: la dimensión aún no está decidida; decide después del OCR.",
        "embedding.quantization.int8": "El índice float32 con {dimension} dimensiones ocupa {size:bytes}; int8 reduce los vectores 4 veces.",
        "embedding.quantization.float32": "El índice float32 con {dimension} dimensiones ocupa {size:bytes}, muy por debajo de 1 GiB; cuantizar cambiaría recall por una memoria que no necesitas ahorrar.",
        "embedding.cost": "{tokens} tokens a embeber (solape, cabeceras repetidas y captions incluidos); los modelos locales no cuestan nada y el mayor modelo de pago cuesta ${usd:.4f} por índice completo.",
        "retrieval.hybrid.undecided": "Evidencia insuficiente: no hay texto en el que medir identificadores; decide después del OCR.",
        "retrieval.hybrid.yes": "{codes} códigos y {ids} identificadores por cada 1k tokens: BM25 encuentra tokens exactos como SKUs y fechas mucho mejor que los vectores densos.",
        "retrieval.hybrid.no": "Solo {codes} códigos y {ids} identificadores por cada 1k tokens; basta con la búsqueda densa.",
        "retrieval.top_k": "Un presupuesto de contexto de {budget} tokens con chunks de hasta {largest} tokens da cabida a {k}.",
        "retrieval.top_k.all": "Son todos los vectores del índice.",
        "retrieval.top_k.rerank": "Recupera {candidates} para que el reranker tenga margen para reordenar.",
        "retrieval.reranker.yes": "{vectors} vectores superan los {threshold}: la primera página de resultados densos se llena de vecinos casi relevantes, y un cross-encoder sobre {candidates} candidatos recupera la precisión.",
        "retrieval.reranker.no": "{vectors} {vectors:vector está|vectores están} por debajo de {threshold}: un top-{k} del índice es suficientemente preciso, y un reranker añadiría una llamada al modelo por candidato. Añádelo si la evaluación muestra fallos.",
        "metadata.source": "source: cada chunk debe citar su fichero.",
        "metadata.chunk_index": "chunk_index: permite ampliar a los chunks vecinos.",
        "metadata.page": "page: las citas apuntan a una página.",
        "metadata.heading_path": "heading_path: los encabezados dan contexto al chunk y sirven de filtro.",
        "metadata.sheet": "sheet: guarda de qué hoja viene cada fila.",
        "metadata.row_range": "row_range: cita las filas exactas.",
        "metadata.language": "language: idiomas mezclados, filtra o enruta por idioma.",
        "metadata.dates": "dates: {dates} fechas por cada 1k tokens, extráelas para filtrar por tiempo.",
        "metadata.doc_kind": "doc_kind: formatos mezclados, filtra tablas, prosa y captions por separado.",
        "bench.chunking.confirmed": "Benchmark ({queries} consultas): {config} obtiene nDCG@{k} {score} [{low}; {high}]; ningún otro candidato la supera por un margen significativo.",
        "bench.chunking.changed": "Benchmark ({queries} consultas): {winner} obtiene nDCG@{k} {score} frente a {score_rule} de {rule}, la elegida por las reglas; la diferencia {gap} [{low}; {high}] excluye el cero, así que gana la medida.",
        "bench.hybrid.better": "Benchmark: añadir BM25 a la búsqueda densa sube nDCG@{k} de {dense} a {hybrid}; la diferencia {gap} [{low}; {high}] excluye el cero. BM25 solo obtiene {bm25}.",
        "bench.hybrid.worse": "Benchmark: la búsqueda densa sola obtiene nDCG@{k} {dense} frente a {hybrid} con BM25 fusionado (diferencia {gap} [{low}; {high}]), así que aquí la búsqueda híbrida no compensa.",
        "bench.hybrid.tie": "Benchmark: la híbrida ({hybrid}) y la densa sola ({dense}) empatan dentro del ruido en nDCG@{k} (el intervalo [{low}; {high}] incluye el cero); decide la regla. BM25 solo obtiene {bm25}.",
        "bench.hybrid.unavailable": "Sin medir: los embeddings densos necesitan el extra bench (pip install 'ragcompass[bench]').",
        "bench.top_k.lower": "Benchmark: recall@{k} ya es {recall}, el {share}% de recall@10 ({recall10}), así que bastan {k} chunks en lugar de {rule_k}.",
        "bench.top_k.confirmed": "Benchmark: hacen falta {k} chunks para llegar al {share}% de recall@10 ({recall10}); recall@{rule_k} es {rule_recall}, así que se mantiene el valor del presupuesto.",
    },
}

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "report": "ragcompass report",
        "summary": "{analysed} of {files} files analysed, {tokens} tokens ({tokenizer}), {pages} pages, languages: {languages}.",
        "recommendations": "Recommendations",
        "documents": "Documents",
        "simulation": "Chunking simulation (recommended size)",
        "simulation_short": "Chunking simulation",
        "index": "Index size",
        "cost": "Embedding cost",
        "summary_llm": "Summary",
        "setting": "Setting",
        "value": "Value",
        "why": "Why",
        "file": "File",
        "kind": "Kind",
        "pages": "Pages",
        "tokens": "Tokens",
        "lang": "Lang",
        "headings": "Headings",
        "tables": "Tables",
        "lists": "Lists",
        "images": "Images",
        "ids": "IDs/1k",
        "structure": "Struct",
        "group": "Group",
        "strategy": "Strategy",
        "size": "Size",
        "overlap": "Overlap",
        "chunks": "Chunks",
        "sentence": "Sentence cuts",
        "table": "Table cuts",
        "orphan": "Orphan headings",
        "code": "Code cuts",
        "tiny": "Tiny",
        "damage": "Damage",
        "dimension": "Dimension",
        "vectors": "Vectors",
        "hnsw": "HNSW graph",
        "model": "Model",
        "per_million": "USD / 1M tokens",
        "usd": "USD",
        "yes": "yes",
        "no": "no",
        "undecided": "undecided",
        "written": "Configuration written to {path}",
        "llm_skipped": "LLM summary skipped: {error}",
        "basis": "Basis",
        "rule-based": "rule-based",
        "measured": "measured",
        "benchmark": "Retrieval benchmark",
        "bench_summary": "{queries} {mode} queries, seed {seed}, k = {k}; retrievers: {retrievers}; dense model: {model}. * marks the rule-based chunking.",
        "config": "Configuration",
        "recall_k": "Recall@{k}",
        "mrr": "MRR",
        "ndcg_k": "nDCG@{k}",
        "index_ms": "Index ms",
        "query_ms": "Query ms",
        "decisions": "Decisions",
        "changed": "changed",
        "confirmed": "kept",
        "warning": "Warning",
        "exported": "evalsmith suite written to {path}",
    },
    "es": {
        "report": "informe de ragcompass",
        "summary": "{analysed} de {files} ficheros analizados, {tokens} tokens ({tokenizer}), {pages} páginas, idiomas: {languages}.",
        "recommendations": "Recomendaciones",
        "documents": "Documentos",
        "simulation": "Simulación de chunking (tamaño recomendado)",
        "simulation_short": "Simulación de chunking",
        "index": "Tamaño del índice",
        "cost": "Coste de embeddings",
        "summary_llm": "Resumen",
        "setting": "Ajuste",
        "value": "Valor",
        "why": "Por qué",
        "file": "Fichero",
        "kind": "Tipo",
        "pages": "Páginas",
        "tokens": "Tokens",
        "lang": "Idioma",
        "headings": "Encabezados",
        "tables": "Tablas",
        "lists": "Listas",
        "images": "Imágenes",
        "ids": "IDs/1k",
        "structure": "Estruct.",
        "group": "Grupo",
        "strategy": "Estrategia",
        "size": "Tamaño",
        "overlap": "Solape",
        "chunks": "Chunks",
        "sentence": "Frases cortadas",
        "table": "Tablas cortadas",
        "orphan": "Encabezados huérfanos",
        "code": "Código cortado",
        "tiny": "Diminutos",
        "damage": "Daño",
        "dimension": "Dimensión",
        "vectors": "Vectores",
        "hnsw": "Grafo HNSW",
        "model": "Modelo",
        "per_million": "USD / 1M tokens",
        "usd": "USD",
        "yes": "sí",
        "no": "no",
        "undecided": "sin decidir",
        "written": "Configuración escrita en {path}",
        "llm_skipped": "Resumen con LLM omitido: {error}",
        "basis": "Base",
        "rule-based": "regla",
        "measured": "medido",
        "benchmark": "Benchmark de recuperación",
        "bench_summary": "{queries} consultas ({mode}), semilla {seed}, k = {k}; retrievers: {retrievers}; modelo denso: {model}. * marca el chunking de las reglas.",
        "config": "Configuración",
        "recall_k": "Recall@{k}",
        "mrr": "MRR",
        "ndcg_k": "nDCG@{k}",
        "index_ms": "Índice ms",
        "query_ms": "Consulta ms",
        "decisions": "Decisiones",
        "changed": "cambiado",
        "confirmed": "mantenido",
        "warning": "Aviso",
        "exported": "Suite de evalsmith escrita en {path}",
    },
}


class Formatter(string.Formatter):
    def __init__(self, lang: str) -> None:
        self.lang = lang

    def format_field(self, value: Any, format_spec: str) -> str:
        if "|" in format_spec:
            singular, plural = format_spec.split("|", 1)
            return singular if value == 1 else plural
        if format_spec == "bytes":
            return self.localize(human_bytes(value))
        if isinstance(value, list):
            return ", ".join(" ".join(self.format_field(item, "") for item in pair) for pair in value)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return super().format_field(value, format_spec)
        if isinstance(value, float) and value.is_integer() and not format_spec:
            text = f"{value:,.1f}"
        elif isinstance(value, int) and format_spec in ("", ",") and abs(value) < 10_000:
            text = str(value)  # no group separator in four-digit numbers: 1024, 3000
        else:
            text = format(value, format_spec or ",")
        return self.localize(text)

    def localize(self, text: str) -> str:
        if self.lang == "es":
            return text.translate(str.maketrans({",": ".", ".": ","}))
        return text


def human_bytes(value: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def render_message(message_id: str, params: dict[str, Any], lang: str) -> str:
    return Formatter(lang).format(MESSAGES[lang][message_id], **params)


def render_parts(parts: list[dict[str, Any]], lang: str) -> str:
    return " ".join(render_message(part["id"], part["params"], lang) for part in parts)


def label(key: str, lang: str, **params: Any) -> str:
    template = LABELS[lang][key]
    return Formatter(lang).format(template, **params) if params else template
