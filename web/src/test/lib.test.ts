import { describe, expect, it } from "vitest";
import { highlight } from "../lib/highlight";
import { health, indexBytes } from "../lib/report";
import { squarify } from "../lib/treemap";
import type { Report } from "../types";
import sample from "./sample-report.json";

const report = sample as unknown as Report;

describe("health", () => {
  it("scores the sample corpus from its measured numbers", () => {
    const { score, parts } = health(report);
    expect(parts.map((p) => p.id)).toEqual(["integrity", "extractable", "parsed"]);
    expect(parts.find((p) => p.id === "parsed")!.score).toBe(20);
    // 21 of 30 vectors come from a text layer; the rest are OCR pages and image captions.
    expect(parts.find((p) => p.id === "extractable")!.score).toBeCloseTo(21, 0);
    expect(score).toBeGreaterThan(70);
    expect(score).toBeLessThanOrEqual(100);
  });

  it("drops the parsed share when files fail", () => {
    const broken = { ...report, documents: report.documents.map((d, i) => (i < 3 ? { ...d, error: "boom" } : d)) };
    expect(health(broken).parts.find((p) => p.id === "parsed")!.score).toBeCloseTo((20 * 6) / 9);
  });
});

describe("indexBytes", () => {
  it("matches the report's own estimate for float32 and int8", () => {
    const row = report.index.find((i) => i.dimension === 1024)!;
    expect(indexBytes(row.vectors, 1024, "float32")).toBe(row.float32_bytes + row.hnsw_overhead_bytes);
    expect(indexBytes(row.vectors, 1024, "int8")).toBe(row.int8_bytes + row.hnsw_overhead_bytes);
  });
});

describe("squarify", () => {
  it("fills the box exactly, largest item first", () => {
    const items = [6, 6, 4, 3, 2, 2, 1];
    const tiles = squarify(items, (v) => v, { x: 0, y: 0, w: 600, h: 400 });
    expect(tiles).toHaveLength(items.length);
    expect(tiles[0].item).toBe(6);
    const area = tiles.reduce((sum, t) => sum + t.w * t.h, 0);
    expect(area).toBeCloseTo(600 * 400, 3);
    for (const t of tiles) {
      expect(t.x).toBeGreaterThanOrEqual(-1e-9);
      expect(t.y).toBeGreaterThanOrEqual(-1e-9);
      expect(t.x + t.w).toBeLessThanOrEqual(600 + 1e-6);
      expect(t.y + t.h).toBeLessThanOrEqual(400 + 1e-6);
      expect(t.w * t.h).toBeCloseTo((t.item / 24) * 600 * 400, 3);
    }
  });

  it("skips empty values", () => {
    expect(squarify([0, 0], (v) => v, { x: 0, y: 0, w: 10, h: 10 })).toEqual([]);
  });
});

describe("highlight", () => {
  it("tokenizes python without losing text", () => {
    const code = 'from x import y  # note\nsplitter = Split(size=512, name="a")\n';
    const tokens = highlight(code, "python");
    expect(tokens.map((t) => t.text).join("")).toBe(code);
    expect(tokens).toContainEqual({ kind: "keyword", text: "from" });
    expect(tokens).toContainEqual({ kind: "comment", text: "# note" });
    expect(tokens).toContainEqual({ kind: "func", text: "Split" });
    expect(tokens).toContainEqual({ kind: "number", text: "512" });
    expect(tokens).toContainEqual({ kind: "string", text: '"a"' });
  });

  it("tokenizes yaml keys and scalars", () => {
    const code = "chunking:\n  documents:\n    size: 256\n    hybrid: true # x\n";
    const tokens = highlight(code, "yaml");
    expect(tokens.map((t) => t.text).join("")).toBe(code);
    expect(tokens.filter((t) => t.kind === "key").map((t) => t.text)).toEqual(["chunking", "documents", "size", "hybrid"]);
    expect(tokens).toContainEqual({ kind: "number", text: "256" });
    expect(tokens).toContainEqual({ kind: "keyword", text: "true" });
  });
});
