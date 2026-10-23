import { FlaskConical, Loader2, Trophy, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useWidth } from "../lib/useWidth";
import { useStore, useT } from "../store";
import type { Bench, BenchConfig, Interval } from "../types";
import { Empty, Panel, PreviewBadge, Segmented, Skeleton, TipRows, useTipProps } from "./ui";

const METRICS = ["recall_at_k", "mrr", "ndcg"] as const;
type Metric = (typeof METRICS)[number];
const MAX_SERIES = 5;

function metricName(metric: Metric, k: number) {
  return metric === "recall_at_k" ? `Recall@${k}` : metric === "mrr" ? "MRR" : `nDCG@${k}`;
}

const fmt = (i: Interval) => `${i.mean.toFixed(3)} [${i.ci[0].toFixed(2)}, ${i.ci[1].toFixed(2)}]`;

function IntervalBars({ configs, metric, k, winner, colorOf }: { configs: BenchConfig[]; metric: Metric; k: number; winner: string; colorOf: (c: BenchConfig) => string }) {
  const t = useT();
  const tip = useTipProps();
  const lo = Math.max(0, Math.floor((Math.min(...configs.map((c) => c[metric].ci[0])) - 0.05) * 10) / 10);
  const x = (v: number) => `${(100 * (v - lo)) / (1 - lo)}%`;
  return (
    <div className="ci-chart">
      <h4>{metricName(metric, k)}</h4>
      <ul>
        {configs.map((c) => (
          <li
            key={c.label}
            className={c.label === winner ? "winner" : ""}
            {...tip(
              <TipRows title={c.label} rows={[[metricName(metric, k), c[metric].mean.toFixed(3)], [t.ci95, `${c[metric].ci[0].toFixed(3)} – ${c[metric].ci[1].toFixed(3)}`], [t.chunks, String(c.chunks)]]} />,
              `${c.label} ${metricName(metric, k)} ${fmt(c[metric])}`,
            )}
          >
            <span className="ci-track">
              <span className="ci-bar" style={{ width: x(c[metric].mean), background: colorOf(c) }} />
              <span className="ci-whisker" style={{ left: x(c[metric].ci[0]), width: `calc(${x(c[metric].ci[1])} - ${x(c[metric].ci[0])})` }} />
            </span>
            <span className="ci-value tabular">{c[metric].mean.toFixed(2)}</span>
          </li>
        ))}
      </ul>
      <div className="ci-axis">
        <span>{lo.toFixed(1)}</span>
        <span>1.0</span>
      </div>
    </div>
  );
}

function RecallCurve({ configs, winner, colorOf }: { configs: BenchConfig[]; winner: string; colorOf: (c: BenchConfig) => string }) {
  const t = useT();
  const tip = useTipProps();
  const [ref, width] = useWidth<HTMLDivElement>(420);
  const ks = [...new Set(configs.flatMap((c) => Object.keys(c.curves.recall).map(Number)))].sort((a, b) => a - b);
  const h = 210;
  const pad = { l: 34, r: 12, t: 10, b: 26 };
  const plotW = width - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const maxK = Math.max(...ks, 1);
  // Square-root k axis spreads 1, 3, 5, 10 evenly enough to read.
  const x = (k: number) => pad.l + (plotW * (Math.sqrt(k) - 1)) / Math.max(0.0001, Math.sqrt(maxK) - 1);
  const y = (v: number) => pad.t + plotH * (1 - v);
  return (
    <div ref={ref} className="chart">
      <svg width={width} height={h} role="group" aria-label={t.recallCurve}>
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={width - pad.r} y1={y(v)} y2={y(v)} className={v ? "grid-line" : "axis-line"} />
            <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" className="axis-text">
              {v}
            </text>
          </g>
        ))}
        {ks.map((k) => (
          <text key={k} x={x(k)} y={h - 8} textAnchor="middle" className="axis-text">
            k={k}
          </text>
        ))}
        {configs.map((c) => {
          const pts = ks.filter((k) => c.curves.recall[k] !== undefined).map((k) => [x(k), y(c.curves.recall[k]), k] as const);
          return (
            <g key={c.label} className={`series${c.label === winner ? " winner" : ""}`}>
              <polyline points={pts.map(([px, py]) => `${px},${py}`).join(" ")} fill="none" stroke={colorOf(c)} className="line" />
              {pts.map(([px, py, k]) => (
                <circle
                  key={k}
                  cx={px}
                  cy={py}
                  r={4}
                  fill={colorOf(c)}
                  className="dot"
                  {...tip(<TipRows title={c.label} rows={[[`Recall@${k}`, c.curves.recall[k].toFixed(3)]]} />, `${c.label} recall at ${k}: ${c.curves.recall[k]}`)}
                />
              ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

const ms = (v: number) => (v >= 100 ? Math.round(v).toString() : v >= 1 ? v.toFixed(1) : v.toFixed(2));

function Latency({ configs, colorOf }: { configs: BenchConfig[]; colorOf: (c: BenchConfig) => string }) {
  const t = useT();
  const max = Math.max(1, ...configs.map((c) => c.query_ms.p95));
  return (
    <table className="latency">
      <thead>
        <tr>
          <th>{t.config}</th>
          <th className="num">{t.indexMs}</th>
          <th>{t.queryMs}</th>
        </tr>
      </thead>
      <tbody>
        {configs.map((c) => (
          <tr key={c.label}>
            <td>
              <span className="swatch" style={{ background: colorOf(c) }} />
              <span className="mono">{c.label}</span>
            </td>
            <td className="num tabular">{ms(c.index_ms)}</td>
            <td>
              <span className="lat-track" title={`mean ${ms(c.query_ms.mean)} ms · p95 ${ms(c.query_ms.p95)} ms`}>
                <span className="lat-p95" style={{ width: `${(100 * c.query_ms.p95) / max}%` }} />
                <span className="lat-mean" style={{ width: `${(100 * c.query_ms.mean) / max}%`, background: colorOf(c) }} />
              </span>
              <span className="tabular lat-text">
                {ms(c.query_ms.mean)} / {ms(c.query_ms.p95)}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function QueryQuality({ bench }: { bench: Bench }) {
  const t = useT();
  const overlap = bench.lexical_overlap;
  const kinds = Object.entries(bench.query_kinds ?? {});
  if (!overlap && !kinds.length && bench.mode === "file") return null;
  const high = (overlap?.mean ?? 0) > 0.5;
  return (
    <div className="quality">
      {overlap && (
        <div className="quality-item" title={t.lexicalOverlapHint}>
          <span className="field-label">{t.lexicalOverlap}</span>
          <span className={`quality-value tabular${high ? " high" : ""}`}>{overlap.mean.toFixed(2)}</span>
          <span className="quality-meter" aria-hidden>
            <span style={{ width: `${Math.min(100, overlap.mean * 100)}%` }} className={high ? "high" : ""} />
            <i style={{ left: "50%" }} />
          </span>
          <span className="quality-kinds muted">
            {Object.entries(overlap.by_kind)
              .map(([k, v]) => `${k} ${v.toFixed(2)}`)
              .join(" · ")}
          </span>
        </div>
      )}
      {kinds.length > 0 && (
        <div className="quality-item">
          <span className="field-label">{t.queryKinds}</span>
          <span className="quality-kinds">
            {kinds.map(([k, n]) => (
              <span key={k} className="kind-chip">
                {k} {n}
              </span>
            ))}
          </span>
        </div>
      )}
      {/* The server may already warn about synthetic queries; say it once. */}
      {bench.mode !== "file" && !bench.warnings.some((w) => w.includes("--queries")) && <p className="quality-note muted">{t.syntheticNote}</p>}
    </div>
  );
}

function Results({ bench }: { bench: Bench }) {
  const t = useT();
  const lang = useStore((s) => s.lang);
  const retrievers = [...new Set(bench.configs.map((c) => c.retriever))];
  const winnerConfig = bench.configs.find((c) => c.label === bench.winner.label);
  const [retriever, setRetriever] = useState(winnerConfig?.retriever ?? retrievers[0]);
  const configs = bench.configs.filter((c) => c.retriever === retriever).slice(0, MAX_SERIES);
  const order = configs.map((c) => c.label);
  const colorOf = (c: BenchConfig) => `var(--series-${order.indexOf(c.label) + 1})`;
  const decision = bench.decisions.find((d) => d.key.startsWith("chunking.")) ?? bench.decisions[0];
  const margin = bench.winner.margin;
  return (
    <>
      <div className="winner-card">
        <Trophy size={18} aria-hidden />
        <div>
          <div className="winner-title">
            <span className="eyebrow">{t.winner}</span>
            <strong className="mono">{bench.winner.label}</strong>
            {bench.winner.significant ? <span className="badge ok">{t.significant}</span> : <span className="badge">{t.notSignificant}</span>}
          </div>
          <p>
            {decision ? (decision.reason_i18n?.[lang] ?? decision.reason) : null}
            {margin && bench.winner.runner_up && (
              <>
                {decision ? " " : ""}
                {t.marginText
                  .replace("{metric}", metricName(bench.primary_metric, bench.k))
                  .replace("{mean}", `+${margin.mean.toFixed(3)}`)
                  .replace("{lo}", margin.ci[0].toFixed(3))
                  .replace("{hi}", margin.ci[1].toFixed(3))
                  .replace("{other}", bench.winner.runner_up)}
              </>
            )}
          </p>
        </div>
        <div className="winner-meta muted">
          {bench.queries} {t.queriesLower} · seed {bench.seed} · {bench.dense_model ?? "BM25"}
        </div>
      </div>
      <QueryQuality bench={bench} />
      {bench.warnings.length > 0 && (
        <p className="inline-warn">
          <TriangleAlert size={14} aria-hidden /> {bench.warnings.join(" ")}
        </p>
      )}
      <div className="bench-toolbar">
        {retrievers.length > 1 && (
          <Segmented size="sm" label={t.retriever} value={retriever} onChange={setRetriever} options={retrievers.map((r) => ({ value: r, label: r }))} />
        )}
        <div className="legend">
          {configs.map((c) => (
            <span key={c.label} className="legend-item">
              <span className="swatch" style={{ background: colorOf(c) }} />
              <span className="mono">{c.label}</span>
              {c.recommended && <span className="badge accent">{t.rule}</span>}
            </span>
          ))}
        </div>
      </div>
      <div className="bench-grid">
        {METRICS.map((m) => (
          <IntervalBars key={m} configs={configs} metric={m} k={bench.k} winner={bench.winner.label} colorOf={colorOf} />
        ))}
      </div>
      <div className="bench-grid two">
        <div>
          <h3 className="chart-title">{t.recallCurve}</h3>
          <RecallCurve configs={configs} winner={bench.winner.label} colorOf={colorOf} />
        </div>
        <div>
          <h3 className="chart-title">{t.latency}</h3>
          <Latency configs={configs} colorOf={colorOf} />
        </div>
      </div>
    </>
  );
}

export function Benchmark() {
  const t = useT();
  const { bench, benchState, benchError, runBench } = useStore();
  return (
    <Panel
      id="bench"
      title={
        <>
          <FlaskConical size={15} aria-hidden /> {t.benchmark}
        </>
      }
      hint={t.benchHint}
      className="span-3"
      actions={bench?.preview && <PreviewBadge />}
    >
      {bench ? (
        <Results bench={bench.data} />
      ) : benchState === "running" ? (
        <div className="bench-loading" role="status" aria-live="polite">
          <p className="muted">
            <Loader2 size={14} className="spin" aria-hidden /> {t.benchRunning}
          </p>
          <div className="bench-grid">
            {METRICS.map((m) => (
              <Skeleton key={m} h={120} />
            ))}
          </div>
        </div>
      ) : (
        <Empty icon={<FlaskConical size={20} />} title={t.benchEmpty}>
          <p>{t.benchEmptyHint}</p>
          {benchState === "error" && (
            <p className="inline-error" role="alert">
              {benchError}
            </p>
          )}
          <button className="button primary" onClick={runBench}>
            {t.runBench}
          </button>
        </Empty>
      )}
    </Panel>
  );
}
