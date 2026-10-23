import { ScanSearch } from "lucide-react";
import { useState } from "react";
import { num } from "../lib/format";
import { groupOf, isPick, picks } from "../lib/report";
import { useWidth } from "../lib/useWidth";
import { useStore, useT } from "../store";
import type { Report, SimulationResult } from "../types";
import { Panel, Segmented, TipRows, useTipProps } from "./ui";

// Fixed slots so a strategy keeps its color in every group and chart.
export const STRATEGY_SLOT: Record<string, number> = { heading: 1, recursive: 2, fixed: 3, page: 4, row: 5 };
const STRATEGY_ORDER = ["heading", "page", "row", "recursive", "fixed"];

function heat(damage: number, max: number) {
  const share = max ? Math.min(1, damage / max) : 0;
  return `color-mix(in oklab, var(--heat) ${Math.round(8 + share * 92)}%, var(--surface))`;
}

function SimTip({ sim, recommended }: { sim: SimulationResult; recommended: boolean }) {
  const t = useT();
  return (
    <TipRows
      title={
        <>
          {sim.strategy} · {sim.size} / {sim.overlap}
          {recommended && <span className="badge accent">{t.recommended}</span>}
        </>
      }
      rows={[
        [t.damage, sim.damage.toFixed(1)],
        [t.chunks, num(sim.chunks)],
        [t.sentence, `${sim.sentence_cut_pct}%`],
        [t.table, `${sim.table_cut_pct}%`],
        [t.orphan, `${sim.orphan_heading_pct}%`],
        [t.code, `${sim.code_cut_pct}%`],
        [t.tiny, `${sim.tiny_pct}%`],
        ["p50 / p95", `${sim.tokens.p50} / ${sim.tokens.p95}`],
      ]}
    />
  );
}

function Heatmap({
  sims,
  pick,
  onFocus,
  onOpen,
}: {
  sims: SimulationResult[];
  pick: SimulationResult | undefined;
  onFocus: (sim: SimulationResult | null) => void;
  onOpen: (sim: SimulationResult) => void;
}) {
  const t = useT();
  const tip = useTipProps();
  const sizes = [...new Set(sims.map((s) => s.size))].sort((a, b) => a - b);
  const strategies = STRATEGY_ORDER.filter((s) => sims.some((x) => x.strategy === s));
  const overlapsOf = (size: number) => [...new Set(sims.filter((s) => s.size === size).map((s) => s.overlap))].sort((a, b) => a - b);
  const levels = Math.max(...sizes.map((size) => overlapsOf(size).length));
  const max = Math.max(1, ...sims.map((s) => s.damage));
  return (
    <div className="heatmap" role="grid" aria-label={t.heatmap} style={{ gridTemplateColumns: `minmax(76px, auto) repeat(${sizes.length * levels}, minmax(34px, 1fr))` }}>
      <div role="row" className="hm-row hm-head">
        <span role="columnheader" />
        {sizes.map((size) => (
          <span key={size} role="columnheader" className="hm-size" style={{ gridColumn: `span ${levels}` }}>
            {size} tok
          </span>
        ))}
      </div>
      <div role="row" className="hm-row hm-sub">
        <span role="columnheader" className="hm-corner">
          {t.overlap}
        </span>
        {sizes.flatMap((size) =>
          Array.from({ length: levels }, (_, i) => (
            <span key={`${size}-${i}`} role="columnheader" className="hm-ov">
              {i === 0 ? "0" : `${Math.round((100 * (overlapsOf(size)[i] ?? 0)) / size)}%`}
            </span>
          )),
        )}
      </div>
      {strategies.map((strategy) => (
        <div role="row" key={strategy} className="hm-row">
          <span role="rowheader" className="hm-strategy">
            <span className="swatch" style={{ background: `var(--series-${STRATEGY_SLOT[strategy]})` }} />
            {strategy}
          </span>
          {sizes.flatMap((size) => {
            const overlaps = overlapsOf(size);
            return Array.from({ length: levels }, (_, i) => {
              const sim = sims.find((s) => s.strategy === strategy && s.size === size && s.overlap === overlaps[i]);
              if (!sim) return <span key={`${size}-${i}`} role="gridcell" className="hm-cell empty" aria-label={t.notApplicable} />;
              const chosen = sim === pick;
              return (
                <button
                  key={`${size}-${i}`}
                  role="gridcell"
                  className={`hm-cell${chosen ? " chosen" : ""}${sim.damage > max * 0.55 ? " dark" : ""}`}
                  style={{ background: heat(sim.damage, max) }}
                  onClick={() => onOpen(sim)}
                  onMouseEnter={() => onFocus(sim)}
                  onMouseLeave={() => onFocus(null)}
                  {...tip(<SimTip sim={sim} recommended={chosen} />, `${strategy} ${size}/${sim.overlap}: ${t.damage} ${sim.damage}`)}
                >
                  {sim.damage < 10 ? sim.damage.toFixed(1) : Math.round(sim.damage)}
                </button>
              );
            });
          })}
        </div>
      ))}
    </div>
  );
}

function DamageBars({ sims, pick }: { sims: SimulationResult[]; pick: SimulationResult | undefined }) {
  const t = useT();
  const tip = useTipProps();
  const [ref, width] = useWidth<HTMLDivElement>(420);
  const sizes = [...new Set(sims.map((s) => s.size))].sort((a, b) => a - b);
  const strategies = STRATEGY_ORDER.filter((s) => sims.some((x) => x.strategy === s));
  // One bar per strategy and size: the lowest-damage overlap, as that is what a user would pick.
  const best = (strategy: string, size: number) =>
    sims.filter((s) => s.strategy === strategy && s.size === size).sort((a, b) => a.damage - b.damage)[0];
  const max = Math.max(10, ...sims.map((s) => s.damage));
  const nice = Math.ceil(max / 50) * 50;
  const h = 200;
  const pad = { l: 34, r: 8, t: 10, b: 26 };
  const plotW = width - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const groupW = plotW / sizes.length;
  const barW = Math.min(26, (groupW * 0.7) / strategies.length - 2);
  const y = (v: number) => pad.t + plotH - (plotH * v) / nice;
  const ticks = [0, nice / 2, nice];
  return (
    <div ref={ref} className="chart">
      <svg width={width} height={h} role="group" aria-label={t.damageBySize}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={width - pad.r} y1={y(v)} y2={y(v)} className={v ? "grid-line" : "axis-line"} />
            <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" className="axis-text">
              {v}
            </text>
          </g>
        ))}
        {sizes.map((size, gi) => {
          const x0 = pad.l + gi * groupW + (groupW - strategies.length * (barW + 2)) / 2;
          return (
            <g key={size}>
              {strategies.map((strategy, si) => {
                const sim = best(strategy, size);
                if (!sim) return null;
                const top = y(sim.damage);
                const bh = Math.max(1.5, pad.t + plotH - top);
                const chosen = pick !== undefined && sim.strategy === pick.strategy && sim.size === pick.size;
                const x = x0 + si * (barW + 2);
                return (
                  <g key={strategy} {...tip(<SimTip sim={sim} recommended={chosen} />, `${strategy} ${size}: ${sim.damage}`)} className="bar-hit">
                    <rect x={x - 1} y={pad.t} width={barW + 2} height={plotH} fill="transparent" />
                    <path
                      d={`M${x},${pad.t + plotH} V${top + Math.min(4, bh)} q0,-${Math.min(4, bh)} ${Math.min(4, bh)},-${Math.min(4, bh)} H${x + barW - Math.min(4, bh)} q${Math.min(4, bh)},0 ${Math.min(4, bh)},${Math.min(4, bh)} V${pad.t + plotH} Z`}
                      fill={`var(--series-${STRATEGY_SLOT[strategy]})`}
                      className="bar"
                    />
                    {chosen && <circle cx={x + barW / 2} cy={top - 8} r="3.5" className="pick-dot" />}
                  </g>
                );
              })}
              <text x={pad.l + gi * groupW + groupW / 2} y={h - 8} textAnchor="middle" className="axis-text">
                {size} tok
              </text>
            </g>
          );
        })}
      </svg>
      <div className="legend">
        {strategies.map((s) => (
          <span key={s} className="legend-item">
            <span className="swatch" style={{ background: `var(--series-${STRATEGY_SLOT[s]})` }} />
            {s}
          </span>
        ))}
        <span className="legend-item">
          <span className="pick-dot-legend" />
          {t.recommended}
        </span>
      </div>
    </div>
  );
}

function Histogram({ sim, recommended }: { sim: SimulationResult; recommended: boolean }) {
  const t = useT();
  const tip = useTipProps();
  const [ref, width] = useWidth<HTMLDivElement>(420);
  const h = 200;
  const pad = { l: 30, r: 8, t: 10, b: 26 };
  const plotW = width - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const hist = sim.histogram;
  if (!hist) {
    // Older servers: show the measured percentiles instead of a histogram.
    const { min, p50, p95, max } = sim.tokens;
    const x = (v: number) => pad.l + (plotW * v) / Math.max(sim.size, max);
    return (
      <div ref={ref} className="chart">
        <svg width={width} height={80} aria-label={t.sizeDistribution}>
          <line x1={x(min)} x2={x(max)} y1={40} y2={40} className="range-line" />
          <rect x={x(p50)} y={30} width={Math.max(2, x(p95) - x(p50))} height={20} rx={4} className="range-box" />
          {[min, p50, p95, max].map((v, i) => (
            <text key={i} x={x(v)} y={70} textAnchor="middle" className="axis-text">
              {v}
            </text>
          ))}
        </svg>
      </div>
    );
  }
  const maxCount = Math.max(1, ...hist.counts);
  const binW = plotW / hist.counts.length;
  const y = (v: number) => pad.t + plotH - (plotH * v) / maxCount;
  return (
    <div ref={ref} className="chart">
      <svg width={width} height={h} role="group" aria-label={`${t.sizeDistribution}: ${sim.strategy} ${sim.size}/${sim.overlap}`}>
        <line x1={pad.l} x2={width - pad.r} y1={pad.t + plotH} y2={pad.t + plotH} className="axis-line" />
        {[0, Math.ceil(maxCount / 2), maxCount].map((v) => (
          <g key={v}>
            {v > 0 && <line x1={pad.l} x2={width - pad.r} y1={y(v)} y2={y(v)} className="grid-line" />}
            <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" className="axis-text">
              {v}
            </text>
          </g>
        ))}
        {hist.counts.map((count, i) => {
          const x = pad.l + i * binW + 1;
          const top = y(count);
          const tiny = hist.edges[i + 1] <= sim.size * 0.25;
          return (
            <g
              key={i}
              className="bar-hit"
              {...tip(
                <TipRows
                  title={`${hist.edges[i]}–${hist.edges[i + 1]}${i === hist.counts.length - 1 ? "+" : ""} tok`}
                  rows={[
                    [t.chunks, String(count)],
                    ...(tiny ? ([[t.tiny, t.yes]] as [string, string][]) : []),
                  ]}
                />,
                `${hist.edges[i]}-${hist.edges[i + 1]} tokens: ${count}`,
              )}
            >
              <rect x={x} y={pad.t} width={binW - 2} height={plotH} fill="transparent" />
              {count > 0 && (
                <rect x={x} y={top} width={binW - 2} height={pad.t + plotH - top} rx={3} className={`bar ${tiny ? "bar-muted" : "bar-accent"}`} />
              )}
            </g>
          );
        })}
        {[0, 0.5, 1].map((f) => {
          const i = Math.round(f * hist.counts.length);
          return (
            <text key={f} x={pad.l + i * binW} y={h - 8} textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"} className="axis-text">
              {hist.edges[i]}
            </text>
          );
        })}
      </svg>
      <div className="chart-caption">
        <span className="mono">
          {sim.strategy} · {sim.size}/{sim.overlap}
        </span>
        {recommended && <span className="badge accent">{t.recommended}</span>}
        <span className="muted">
          p50 {sim.tokens.p50} · p95 {sim.tokens.p95} · {num(sim.chunks)} {t.chunksLower}
        </span>
      </div>
    </div>
  );
}

export function Chunking({ report }: { report: Report }) {
  const t = useT();
  const openExplorer = useStore((s) => s.openExplorer);
  const chosen = picks(report);
  const groups = [...new Set(report.simulations.map((s) => s.group))];
  const [group, setGroup] = useState(groups[0] ?? "documents");
  const [focus, setFocus] = useState<SimulationResult | null>(null);
  if (!groups.length) return null;
  const sims = report.simulations.filter((s) => s.group === group);
  const pick = sims.find((s) => isPick(s, chosen[group]));
  const sample = [...report.documents].filter((d) => d.tokens > 0 && groupOf(d.kind) === group).sort((a, b) => b.tokens - a.tokens)[0];
  const open = (sim: SimulationResult) =>
    sample && openExplorer({ file: sample.path, strategy: sim.strategy, size: sim.size, overlap: sim.overlap });
  const shown = focus ?? pick ?? sims[0];

  return (
    <Panel
      id="chunking"
      title={t.simulation}
      hint={t.simulationHint}
      className="span-3"
      actions={
        groups.length > 1 && (
          <Segmented size="sm" label={t.group} value={group} onChange={(g) => (setGroup(g), setFocus(null))} options={groups.map((g) => ({ value: g, label: t.groups[g] ?? g }))} />
        )
      }
    >
      <div className="chunking-grid">
        <div className="chunking-heat">
          <h3 className="chart-title">
            {t.heatmap}
            {sample && (
              <span className="chart-title-hint">
                <ScanSearch size={12} aria-hidden /> {t.heatmapHint}
              </span>
            )}
          </h3>
          <Heatmap sims={sims} pick={pick} onFocus={setFocus} onOpen={open} />
          <div className="legend">
            <span className="legend-item ramp">
              {t.lowDamage}
              <span className="ramp-bar" />
              {t.highDamage}
            </span>
            <span className="legend-item">
              <span className="swatch ring" />
              {t.recommended}
            </span>
          </div>
        </div>
        <div>
          <h3 className="chart-title">{t.damageBySize}</h3>
          <DamageBars sims={sims} pick={pick} />
        </div>
        <div>
          <h3 className="chart-title">{t.sizeDistribution}</h3>
          {shown && <Histogram sim={shown} recommended={shown === pick} />}
        </div>
      </div>
    </Panel>
  );
}
