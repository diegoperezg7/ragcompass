import { Orbit } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ApiError, fetchProjection } from "../api";
import { useWidth } from "../lib/useWidth";
import { useStore, useT } from "../store";
import type { Projection as ProjectionData, Report } from "../types";
import { Empty, Panel, Skeleton, TipRows, useTipProps } from "./ui";

// Five colored files plus a gray "other": more hues would stop being distinguishable.
const MAX_FILES = 5;

export function Projection({ report }: { report: Report }) {
  const t = useT();
  const { openExplorer, expire } = useStore();
  const tip = useTipProps();
  const [state, setState] = useState<{ data?: ProjectionData; error?: "extra" | "failed" }>({});
  const [query, setQuery] = useState(0);
  const [ref, width] = useWidth<HTMLDivElement>(640);

  useEffect(() => {
    let live = true;
    fetchProjection(report)
      .then((data) => live && setState({ data }))
      .catch((error: ApiError) => {
        if (!live) return;
        if (error.expired) expire();
        else setState({ error: error.status === 501 ? "extra" : "failed" });
      });
    return () => {
      live = false;
    };
  }, [report, expire]);

  const data = state.data;
  const files = useMemo(() => {
    const counts = new Map<string, number>();
    data?.points.forEach((p) => counts.set(p.file, (counts.get(p.file) ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([f]) => f);
  }, [data]);
  const colorOf = (file: string) => {
    const i = files.indexOf(file);
    return i < MAX_FILES ? `var(--series-${i + 1})` : "var(--series-other)";
  };

  const h = Math.max(280, Math.min(380, Math.round(width * 0.5)));
  const pad = 18;
  const sx = (v: number) => pad + ((v + 1) / 2) * (width - 2 * pad);
  const sy = (v: number) => pad + ((1 - v) / 2) * (h - 2 * pad);
  const q = data?.queries[query];
  const neighbors = new Set(q?.neighbors ?? []);

  return (
    <Panel
      id="projection"
      title={
        <>
          <Orbit size={15} aria-hidden /> {t.projection}
        </>
      }
      hint={data ? `${t.projectionHint} ${data.model} · PCA ${(100 * (data.explained_variance[0] + data.explained_variance[1])).toFixed(0)}% ${t.varianceLower}` : t.projectionHint}
      className="span-2"
    >
      {state.error ? (
        <Empty icon={<Orbit size={20} />} title={state.error === "extra" ? t.projectionExtra : t.projectionFailed}>
          {state.error === "extra" && <code>pip install "ragcompass[bench]"</code>}
        </Empty>
      ) : !data ? (
        <Skeleton h={300} />
      ) : (
        <>
          {data.queries.length > 0 && (
            <div className="query-picker">
              <label htmlFor="projection-query" className="muted">
                {t.query}
              </label>
              <select id="projection-query" className="select" value={query} onChange={(e) => setQuery(Number(e.target.value))}>
                {data.queries.map((x, i) => (
                  <option key={x.id} value={i}>
                    {x.text}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div ref={ref} className="scatter-wrap">
            <svg width={width} height={h} className="scatter" role="group" aria-label={t.projection}>
              <line x1={sx(0)} x2={sx(0)} y1={pad} y2={h - pad} className="grid-line" />
              <line x1={pad} x2={width - pad} y1={sy(0)} y2={sy(0)} className="grid-line" />
              {q &&
                data.points
                  .filter((p) => neighbors.has(p.id))
                  .map((p) => <line key={p.id} x1={sx(q.x)} y1={sy(q.y)} x2={sx(p.x)} y2={sy(p.y)} className="neighbor-line" />)}
              {data.points.map((p) => {
                const near = neighbors.has(p.id);
                return (
                  <circle
                    key={p.id}
                    cx={sx(p.x)}
                    cy={sy(p.y)}
                    r={near ? 6 : 4.5}
                    fill={colorOf(p.file)}
                    className={`point${near ? " near" : ""}${q && !near ? " faded" : ""}`}
                    onClick={() => openExplorer({ file: p.file, strategy: data.strategy, size: data.size, overlap: data.overlap, focus: p.chunk_index })}
                    {...tip(
                      <>
                        <TipRows title={`${p.file} · #${p.chunk_index + 1}`} rows={[[t.tokens, String(p.tokens)]]} />
                        <p className="tip-text">{p.preview}</p>
                      </>,
                      `${p.file} chunk ${p.chunk_index + 1}`,
                    )}
                  />
                );
              })}
              {q && (
                <g transform={`translate(${sx(q.x)},${sy(q.y)})`} className="query-mark" {...tip(<TipRows title={t.query} rows={[[q.text, ""]]} />, `${t.query}: ${q.text}`)}>
                  <rect x={-6} y={-6} width={12} height={12} transform="rotate(45)" />
                </g>
              )}
            </svg>
          </div>
          <div className="legend">
            {files.slice(0, MAX_FILES).map((f) => (
              <span key={f} className="legend-item">
                <span className="swatch round" style={{ background: colorOf(f) }} />
                {f}
              </span>
            ))}
            {files.length > MAX_FILES && (
              <span className="legend-item">
                <span className="swatch round" style={{ background: "var(--series-other)" }} />
                {t.otherFiles.replace("{n}", String(files.length - MAX_FILES))}
              </span>
            )}
            {q && (
              <span className="legend-item">
                <span className="swatch diamond" />
                {t.queryAndNeighbors}
              </span>
            )}
          </div>
        </>
      )}
    </Panel>
  );
}
