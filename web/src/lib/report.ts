import type { Recommendation, Report, SimulationResult } from "../types";

export interface ChunkPick {
  strategy: string;
  size: number;
  overlap: number;
}

export function rec(report: Report, key: string): Recommendation | undefined {
  return report.recommendations.find((r) => r.key === key);
}

export function picks(report: Report): Record<string, ChunkPick> {
  const out: Record<string, ChunkPick> = {};
  for (const r of report.recommendations) {
    if (r.key.startsWith("chunking.") && r.value) out[r.key.slice(9)] = r.value as ChunkPick;
  }
  return out;
}

export function isPick(sim: SimulationResult, pick: ChunkPick | undefined): boolean {
  return Boolean(pick) && sim.strategy === pick!.strategy && sim.size === pick!.size && sim.overlap === pick!.overlap;
}

/** Recommendations picked by running the chunkers on the corpus, as opposed to a rule over its profile. */
export const isMeasured = (key: string) => key.startsWith("chunking.") || key === "vectors";

export interface HealthPart {
  id: "integrity" | "extractable" | "parsed";
  score: number;
  max: number;
}

/**
 * Corpus health, 0-100, from numbers the report already has:
 * - integrity (50): damage of the recommended chunking, weighted by chunks (100 damage -> 0 points);
 * - extractable (30): share of vectors that come from a text layer rather than OCR or vision;
 * - parsed (20): share of files that parsed without error.
 */
export function health(report: Report): { score: number; parts: HealthPart[] } {
  let chunks = 0;
  let damage = 0;
  for (const [group, pick] of Object.entries(picks(report))) {
    const sim = report.simulations.find((s) => s.group === group && isPick(s, pick));
    if (sim) {
      chunks += sim.chunks;
      damage += sim.damage * sim.chunks;
    }
  }
  const avgDamage = chunks ? damage / chunks : 0;
  const evidence = rec(report, "vectors")?.evidence as { simulated?: number; images?: number; scanned_estimate?: number } | undefined;
  const simulated = evidence?.simulated ?? 0;
  const vectors = simulated + (evidence?.images ?? 0) + (evidence?.scanned_estimate ?? 0);
  const files = report.summary.files || 1;
  const failed = report.documents.filter((d) => d.error).length;
  const parts: HealthPart[] = [
    { id: "integrity", max: 50, score: 50 * (1 - Math.min(1, avgDamage / 100)) },
    { id: "extractable", max: 30, score: vectors ? (30 * simulated) / vectors : 30 },
    { id: "parsed", max: 20, score: (20 * (files - failed)) / files },
  ];
  return { score: Math.round(parts.reduce((sum, p) => sum + p.score, 0)), parts };
}

export const QUANTIZATION_BYTES = { float32: 4, float16: 2, int8: 1, binary: 1 / 8 } as const;
export type Quantization = keyof typeof QUANTIZATION_BYTES;
export const DIMENSIONS = [384, 768, 1024, 1536, 3072];
/** HNSW graph links per vector (M = 16, two layers' worth of 4-byte ids), as the report assumes. */
export const HNSW_BYTES_PER_VECTOR = 128;

export function indexBytes(vectors: number, dimension: number, quantization: Quantization): number {
  return vectors * (dimension * QUANTIZATION_BYTES[quantization] + HNSW_BYTES_PER_VECTOR);
}

/** Token counts per document kind, for the composition chart. */
export function tokensByKind(report: Report): { kind: string; tokens: number; files: number }[] {
  const map = new Map<string, { kind: string; tokens: number; files: number }>();
  for (const d of report.documents) {
    const entry = map.get(d.kind) ?? { kind: d.kind, tokens: 0, files: 0 };
    entry.tokens += d.tokens;
    entry.files += 1;
    map.set(d.kind, entry);
  }
  return [...map.values()].sort((a, b) => b.tokens - a.tokens || b.files - a.files);
}

export function groupOf(kind: string): string | null {
  if (["pdf_text", "pdf_mixed", "docx", "markdown", "html", "text"].includes(kind)) return "documents";
  if (["csv", "xlsx"].includes(kind)) return "tables";
  if (kind === "code") return "code";
  return null;
}
