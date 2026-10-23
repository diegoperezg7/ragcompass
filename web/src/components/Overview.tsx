import { Activity, ArrowRight, Check, FileStack, FlaskConical, Loader2, ScanText, Scale, SplitSquareHorizontal, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { bytes, compact, num, usd } from "../lib/format";
import { health, indexBytes, rec, type Quantization } from "../lib/report";
import { useStore, useT } from "../store";
import type { Report } from "../types";

function Step({
  icon,
  label,
  value,
  detail,
  state,
  action,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  detail: ReactNode;
  state: "done" | "warn" | "todo" | "running";
  action?: ReactNode;
}) {
  return (
    <li className={`pipe-step ${state}`}>
      <div className="pipe-top">
        <span className="pipe-icon" aria-hidden>
          {icon}
        </span>
        <span className="pipe-label">{label}</span>
        <span className={`pipe-state ${state}`} aria-hidden>
          {state === "done" && <Check size={12} strokeWidth={3} />}
          {state === "warn" && <TriangleAlert size={12} strokeWidth={2.5} />}
          {state === "running" && <Loader2 size={12} className="spin" />}
        </span>
      </div>
      <div className="pipe-value">{value}</div>
      <div className="pipe-detail">{detail}</div>
      {action}
    </li>
  );
}

export function Pipeline({ report }: { report: Report }) {
  const t = useT();
  const { bench, benchState, runBench } = useStore();
  const s = report.summary;
  const failed = report.documents.filter((d) => d.error).length;
  const totalBytes = report.documents.reduce((sum, d) => sum + d.size_bytes, 0);
  const strategies = new Set(report.simulations.map((x) => x.strategy)).size;
  const settings = report.recommendations.filter((r) => !r.key.startsWith("parser.")).length;
  const best = bench?.data.configs.find((c) => c.label === bench.data.winner.label);
  return (
    <ol className="pipeline" aria-label={t.pipeline}>
      <Step
        icon={<FileStack size={15} />}
        label={t.steps.ingest}
        value={`${s.analysed}/${s.files} ${t.filesLower}`}
        detail={failed ? `${failed} ${t.failedLower}` : bytes(totalBytes)}
        state={failed ? "warn" : "done"}
      />
      <Step
        icon={<ScanText size={15} />}
        label={t.steps.profile}
        value={`${compact(s.tokens)} ${t.tokensLower}`}
        detail={`${Object.keys(s.languages).length} ${t.langsLower} · ${s.pages} ${t.pagesLower}`}
        state="done"
      />
      <Step
        icon={<SplitSquareHorizontal size={15} />}
        label={t.steps.simulate}
        value={`${report.simulations.length} ${t.runsLower}`}
        detail={`${strategies} ${t.strategiesLower} · 3 ${t.sizesLower}`}
        state="done"
      />
      <Step
        icon={<Scale size={15} />}
        label={t.steps.rules}
        value={`${settings} ${t.settingsLower}`}
        detail={`${report.recommendations.length - settings} ${t.parsersLower}`}
        state="done"
      />
      <Step
        icon={<FlaskConical size={15} />}
        label={t.steps.bench}
        value={best ? `nDCG ${best.ndcg.mean.toFixed(2)}` : benchState === "running" ? t.running : t.notRun}
        detail={bench ? `${bench.data.configs.length} ${t.configsLower} · ${bench.data.queries} ${t.queriesLower}` : t.benchStepHint}
        state={bench ? "done" : benchState === "running" ? "running" : "todo"}
        action={
          !bench && benchState !== "running" ? (
            <button className="link-button" onClick={runBench}>
              {t.runBench} <ArrowRight size={13} aria-hidden />
            </button>
          ) : undefined
        }
      />
    </ol>
  );
}

function Gauge({ score }: { score: number }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const arc = 0.75; // a 270 degree track
  const tone = score >= 75 ? "good" : score >= 50 ? "fair" : "poor";
  return (
    <svg className={`gauge ${tone}`} viewBox="0 0 128 128" width="148" height="148" aria-hidden>
      <circle cx="64" cy="64" r={r} className="gauge-track" strokeDasharray={`${c * arc} ${c}`} transform="rotate(135 64 64)" />
      <circle
        cx="64"
        cy="64"
        r={r}
        className="gauge-value"
        strokeDasharray={`${(c * arc * score) / 100} ${c}`}
        transform="rotate(135 64 64)"
      />
      <text x="64" y="66" textAnchor="middle" className="gauge-number">
        {score}
      </text>
      <text x="64" y="86" textAnchor="middle" className="gauge-unit">
        / 100
      </text>
    </svg>
  );
}

export function Overview({ report }: { report: Report }) {
  const t = useT();
  const { score, parts } = health(report);
  const tone = score >= 75 ? t.healthGood : score >= 50 ? t.healthFair : t.healthPoor;
  const vectors = (rec(report, "vectors")?.value as number) ?? 0;
  const dimension = (rec(report, "embedding.dimension")?.value as number) ?? 1024;
  const quantization = ((rec(report, "embedding.quantization")?.value as string) ?? "float32") as Quantization;
  const paid = report.costs.filter((c) => c.usd_per_million > 0);
  const maxCost = Math.max(0, ...paid.map((c) => c.usd));
  const s = report.summary;
  const langs = Object.entries(s.languages).sort((a, b) => b[1] - a[1]);
  const kpis: { label: string; value: ReactNode; detail: ReactNode }[] = [
    { label: t.files, value: num(s.analysed), detail: `${Object.keys(s.kinds).length} ${t.kindsLower}` },
    { label: t.tokens, value: compact(s.tokens), detail: s.tokenizer },
    { label: t.vectors, value: num(vectors), detail: t.vectorsDetail },
    {
      label: t.indexSize,
      value: bytes(indexBytes(vectors, dimension, quantization)),
      detail: `${dimension}d · ${quantization} · HNSW`,
    },
    { label: t.embedCost, value: usd(maxCost), detail: t.costDetail },
    { label: t.languages, value: langs.map(([l]) => l.toUpperCase()).join(" ") || "n/a", detail: `${langs.length} ${t.detectedLower}` },
  ];
  return (
    <div className="grid overview">
      <section className="panel health" aria-labelledby="health-title">
        <header className="panel-head">
          <div className="panel-titles">
            <h2 id="health-title">
              <Activity size={15} aria-hidden /> {t.health}
            </h2>
            <p className="panel-hint">{t.healthHint}</p>
          </div>
        </header>
        <div className="health-body">
          <div className="gauge-wrap">
            <Gauge score={score} />
            <span className="gauge-tone">{tone}</span>
          </div>
          <ul className="health-parts">
            {parts.map((p) => (
              <li key={p.id}>
                <div className="health-part-head">
                  <span>{t.healthParts[p.id]}</span>
                  <span className="tabular">
                    {Math.round(p.score)}
                    <span className="muted">/{p.max}</span>
                  </span>
                </div>
                <div className="meter" aria-hidden>
                  <span style={{ width: `${(100 * p.score) / p.max}%` }} />
                </div>
                <p className="health-part-hint">{t.healthPartHints[p.id]}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>
      <dl className="kpis">
        {kpis.map((k) => (
          <div key={k.label} className="kpi">
            <dt>{k.label}</dt>
            <dd className="kpi-value">{k.value}</dd>
            <dd className="kpi-detail">{k.detail}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
