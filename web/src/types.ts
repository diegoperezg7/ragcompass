export interface Identifiers {
  codes: number;
  dates: number;
  numbers: number;
  per_1k_tokens: number;
  codes_per_1k_tokens: number;
}

export interface DocProfile {
  path: string;
  kind: string;
  size_bytes: number;
  pages: number | null;
  scanned_pages: number;
  chars: number;
  tokens: number;
  language: string | null;
  headings: number;
  tables: number;
  table_rows: number;
  list_items: number;
  code_blocks: number;
  images: number;
  images_per_page: number | null;
  image_text_ratio: number;
  identifiers: Identifiers;
  error: string | null;
  warnings?: string[];
}

export interface SimulationResult {
  group: string;
  strategy: string;
  size: number;
  overlap: number;
  chunks: number;
  tokens: { min: number; p50: number; p95: number; max: number; mean: number };
  total_tokens: number;
  overhead_pct: number;
  sentence_cut_pct: number;
  table_cut_pct: number;
  orphan_heading_pct: number;
  code_cut_pct: number;
  tiny_pct: number;
  damage: number;
  /** Ten equal bins from 0 to `size`; the last one also counts larger chunks. */
  histogram?: { edges: number[]; counts: number[] };
}

export interface Recommendation {
  key: string;
  value: unknown;
  reason: string;
  reason_i18n: Record<string, string>;
  reason_parts: { id: string; params: Record<string, unknown> }[];
  evidence: Record<string, unknown>;
  basis?: "rule-based" | "measured";
}

export interface IndexEstimate {
  dimension: number;
  vectors: number;
  float32_bytes: number;
  int8_bytes: number;
  hnsw_overhead_bytes: number;
}

export interface EmbeddingCost {
  model: string;
  usd_per_million: number;
  tokens: number;
  usd: number;
}

export interface Report {
  version: string;
  /** report_id: the server keeps the analysis for a while so the explorer, bench and export can use it. */
  id?: string;
  lang?: string;
  bench?: Bench | null;
  summary: {
    root: string;
    files: number;
    analysed: number;
    tokens: number;
    pages: number;
    kinds: Record<string, number>;
    languages: Record<string, number>;
    tokenizer: string;
  };
  documents: DocProfile[];
  simulations: SimulationResult[];
  recommendations: Recommendation[];
  index: IndexEstimate[];
  costs: EmbeddingCost[];
  config: Record<string, unknown>;
  llm_summary: string | null;
}

export type IssueKind = "sentence_cut" | "table_cut" | "orphan_heading" | "code_cut" | "tiny";
export type Boundary = "clean" | "sentence" | "table_row" | "code";

export interface ChunkSpan {
  index: number;
  start: number;
  end: number;
  tokens: number;
  extra_tokens: number;
  issues: { kind: IssueKind; detail?: string }[];
  boundaries: { start: Boundary; end: Boundary };
}

export interface ChunkView {
  report_id: string;
  file: string;
  kind: string;
  group: string;
  strategy: string;
  applied_strategy: string;
  size: number;
  overlap: number;
  recommended: boolean;
  strategies: string[];
  text: string;
  blocks: { type: string; start: number; end: number; level?: number | null; page?: number | null }[];
  chunks: ChunkSpan[];
  metrics: SimulationResult;
}

export interface Interval {
  mean: number;
  ci: [number, number];
}

export interface BenchConfig {
  label: string;
  group: string;
  strategy: string;
  size: number;
  overlap: number;
  retriever: "bm25" | "dense" | "hybrid";
  recommended: boolean;
  chunks: number;
  recall_at_k: Interval;
  mrr: Interval;
  ndcg: Interval;
  curves: { recall: Record<string, number> };
  index_ms: number;
  query_ms: { mean: number; p95: number };
}

export interface BenchDecision {
  key: string;
  basis: "rule-based" | "measured";
  rule_value: unknown;
  measured_value: unknown;
  changed: boolean;
  reason: string;
  reason_i18n: Record<string, string>;
}

export interface Bench {
  k: number;
  seed: number;
  queries: number;
  mode: "template" | "llm" | "file" | string;
  query_kinds?: Record<string, number>;
  /** IDF-weighted share of each source's vocabulary its query repeats; high values favour BM25. */
  lexical_overlap?: { mean: number; by_kind: Record<string, number> };
  retrievers: string[];
  dense_model: string | null;
  warnings: string[];
  primary_metric: "ndcg" | "mrr" | "recall_at_k";
  configs: BenchConfig[];
  winner: { label: string; runner_up: string | null; significant: boolean; margin: Interval | null };
  decisions: BenchDecision[];
  sample_queries: { id: string; text: string; file: string; start: number; end: number }[];
  elapsed_ms: number;
}

export interface ProjectedChunk {
  id: number;
  file: string;
  chunk_index: number;
  x: number;
  y: number;
  tokens: number;
  preview: string;
}

export interface Projection {
  model: string;
  group: string;
  strategy: string;
  size: number;
  overlap: number;
  explained_variance: [number, number];
  points: ProjectedChunk[];
  queries: { id: string; text: string; x: number; y: number; neighbors: number[] }[];
}

export type ExportTarget = "yaml" | "langchain" | "llamaindex" | "haystack";
