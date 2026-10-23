import { useEffect, useMemo, useState } from "react";
import { fetchChunks } from "../api";
import { compact, num } from "../lib/format";
import { groupOf, tokensByKind } from "../lib/report";
import { squarify } from "../lib/treemap";
import { useWidth } from "../lib/useWidth";
import { useStore, useT } from "../store";
import type { DocProfile, Report } from "../types";
import { Panel, Segmented, TipRows, useTipProps } from "./ui";

// Files without a text layer still cost vectors: size them by the report's own estimates.
const SCANNED_PAGE_TOKENS = 800;
const CAPTION_TOKENS = 100;

type Category = "documents" | "tables" | "code" | "visual";
const CATEGORIES: Category[] = ["documents", "tables", "code", "visual"];

function category(doc: DocProfile): Category {
  return (groupOf(doc.kind) as Category | null) ?? "visual";
}

function weight(doc: DocProfile) {
  if (doc.tokens) return { value: doc.tokens, estimated: false };
  const estimate = doc.scanned_pages * SCANNED_PAGE_TOKENS + doc.images * CAPTION_TOKENS || CAPTION_TOKENS;
  return { value: estimate, estimated: true };
}

const fileName = (path: string) => path.split("/").pop() ?? path;
const MAX_DAMAGE_FILES = 60;

/** Per-file damage of the recommended chunking, from the explorer endpoint. */
function useFileDamage(report: Report, enabled: boolean) {
  const [damage, setDamage] = useState<Record<string, number> | null>(null);
  useEffect(() => {
    if (!enabled || damage || !report.id) return;
    const controller = new AbortController();
    const docs = report.documents
      .filter((d) => d.tokens > 0 && groupOf(d.kind))
      .sort((a, b) => b.tokens - a.tokens)
      .slice(0, MAX_DAMAGE_FILES);
    Promise.all(
      docs.map((d) =>
        fetchChunks(report, { file: d.path }, controller.signal)
          .then((v) => [d.path, v.metrics.damage] as const)
          .catch(() => null),
      ),
    ).then((rows) => {
      if (!controller.signal.aborted) setDamage(Object.fromEntries(rows.filter((r) => r !== null)));
    });
    return () => controller.abort();
  }, [enabled, damage, report]);
  return damage;
}

function damageColor(value: number) {
  const share = Math.min(1, value / 120);
  return `color-mix(in oklab, var(--heat) ${Math.round(14 + share * 86)}%, var(--surface))`;
}

export function CorpusMap({ report }: { report: Report }) {
  const t = useT();
  const openExplorer = useStore((s) => s.openExplorer);
  const [mode, setMode] = useState<"kind" | "damage">("kind");
  const [ref, width] = useWidth<HTMLDivElement>();
  const tip = useTipProps();
  const damage = useFileDamage(report, mode === "damage");
  const height = Math.max(220, Math.min(300, Math.round(width * 0.36)));
  const tiles = useMemo(
    () => squarify(report.documents, (d) => weight(d).value, { x: 0, y: 0, w: width, h: height }),
    [report.documents, width, height],
  );
  const total = report.documents.reduce((sum, d) => sum + weight(d).value, 0);
  const present = CATEGORIES.filter((c) => report.documents.some((d) => category(d) === c));

  return (
    <Panel
      id="corpus-map"
      title={t.corpusMap}
      hint={t.corpusMapHint}
      className="span-2"
      actions={
        <Segmented
          size="sm"
          label={t.colorBy}
          value={mode}
          onChange={setMode}
          options={[
            { value: "kind", label: t.byKind },
            { value: "damage", label: t.byDamage },
          ]}
        />
      }
    >
      <div ref={ref} className="treemap-wrap">
        <svg width={width} height={height} className="treemap" role="group" aria-label={t.corpusMap}>
          <defs>
            <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" className="hatch-line" />
            </pattern>
          </defs>
          {tiles.map(({ x, y, w, h, item: doc }) => {
            const { value, estimated } = weight(doc);
            const fileDamage = damage?.[doc.path];
            const fill =
              mode === "damage"
                ? fileDamage === undefined
                  ? "var(--surface-sunken)"
                  : damageColor(fileDamage)
                : `color-mix(in oklab, var(--cat-${category(doc)}) 20%, var(--surface))`;
            const explorable = doc.tokens > 0 && groupOf(doc.kind) !== null;
            const showLabel = w > 70 && h > 34;
            const share = (100 * value) / total;
            return (
              <g
                key={doc.path}
                className={`tile${explorable ? " clickable" : ""}`}
                transform={`translate(${x},${y})`}
                onClick={() => explorable && openExplorer({ file: doc.path })}
                onKeyDown={(e) => {
                  if (explorable && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    openExplorer({ file: doc.path });
                  }
                }}
                role={explorable ? "button" : "img"}
                {...tip(
                  <TipRows
                    title={doc.path}
                    rows={[
                      [t.kind, doc.kind],
                      [estimated ? t.estimatedTokens : t.tokens, num(value)],
                      [t.share, `${share.toFixed(1)}%`],
                      ...(fileDamage !== undefined ? ([[t.damage, fileDamage.toFixed(1)]] as [string, string][]) : []),
                      ...(explorable ? ([[t.clickToExplore, ""]] as [string, string][]) : []),
                    ]}
                  />,
                  `${doc.path}, ${doc.kind}, ${num(value)} ${t.tokensLower}`,
                )}
              >
                <rect width={Math.max(0, w - 2)} height={Math.max(0, h - 2)} rx="4" fill={fill} className="tile-rect" />
                {estimated && <rect width={Math.max(0, w - 2)} height={Math.max(0, h - 2)} rx="4" fill="url(#hatch)" />}
                {mode === "kind" && <rect width={Math.max(0, w - 2)} height={Math.min(3, h - 2)} rx="1.5" fill={`var(--cat-${category(doc)})`} />}
                {showLabel && (
                  <>
                    <text x="10" y="20" className="tile-name">
                      {fileName(doc.path).length * 7 > w - 16 ? fileName(doc.path).slice(0, Math.max(3, Math.floor((w - 16) / 7) - 1)) + "…" : fileName(doc.path)}
                    </text>
                    {h > 50 && (
                      <text x="10" y="37" className="tile-meta">
                        {estimated ? "~" : ""}
                        {compact(value)} tok · {share.toFixed(0)}%
                      </text>
                    )}
                  </>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="legend">
        {mode === "kind" ? (
          <>
            {present.map((c) => (
              <span key={c} className="legend-item">
                <span className="swatch" style={{ background: `var(--cat-${c})` }} />
                {t.categories[c]}
              </span>
            ))}
            <span className="legend-item">
              <span className="swatch hatched" />
              {t.estimatedLegend}
            </span>
          </>
        ) : (
          <span className="legend-item ramp">
            {t.lowDamage}
            <span className="ramp-bar" />
            {t.highDamage}
            {!damage && report.id && <span className="muted"> · {t.loading}</span>}
          </span>
        )}
      </div>
    </Panel>
  );
}

export function Composition({ report }: { report: Report }) {
  const t = useT();
  const rows = tokensByKind(report);
  const max = Math.max(1, ...rows.map((r) => r.tokens));
  const total = rows.reduce((sum, r) => sum + r.tokens, 0) || 1;
  const tip = useTipProps();
  return (
    <Panel id="composition" title={t.composition} hint={t.compositionHint}>
      <ul className="hbars">
        {rows.map((r) => {
          const cat = (groupOf(r.kind) ?? "visual") as Category;
          return (
            <li
              key={r.kind}
              className="hbar"
              {...tip(
                <TipRows
                  title={r.kind}
                  rows={[
                    [t.files, String(r.files)],
                    [t.tokens, num(r.tokens)],
                    [t.share, `${((100 * r.tokens) / total).toFixed(1)}%`],
                  ]}
                />,
                `${r.kind}: ${r.files} ${t.filesLower}, ${num(r.tokens)} ${t.tokensLower}`,
              )}
            >
              <span className="hbar-label">
                <span className="swatch" style={{ background: `var(--cat-${cat})` }} />
                {r.kind}
                <span className="muted">×{r.files}</span>
              </span>
              <span className="hbar-track">
                <span className="hbar-fill" style={{ width: `${(100 * r.tokens) / max}%`, background: `var(--cat-${cat})` }} />
              </span>
              <span className="hbar-value tabular">{r.tokens ? compact(r.tokens) : t.noText}</span>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
