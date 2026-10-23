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
}

export interface Recommendation {
  key: string;
  value: unknown;
  reason: string;
  reason_i18n: Record<string, string>;
  reason_parts: { id: string; params: Record<string, unknown> }[];
  evidence: Record<string, unknown>;
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
