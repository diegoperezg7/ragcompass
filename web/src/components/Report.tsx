import {
  Binary,
  Blocks,
  Database,
  Download,
  FileText,
  Layers,
  RotateCcw,
  ScanText,
  Search,
  Tags,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { keyLabel } from "../i18n";
import { useStore, useT } from "../store";
import type { Recommendation, Report as ReportData, SimulationResult } from "../types";

const SECTION_ICONS: Record<string, ReactNode> = {
  parser: <ScanText size={16} />,
  chunking: <Blocks size={16} />,
  vectors: <Layers size={16} />,
  embedding: <Binary size={16} />,
  retrieval: <Search size={16} />,
  metadata: <Tags size={16} />,
};

function bytes(value: number): string {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return i === 0 ? `${value} B` : `${value.toFixed(1)} ${units[i]}`;
}

const num = (value: number) => value.toLocaleString("en-US");

function useFormatValue() {
  const t = useT();
  return (rec: Recommendation): ReactNode => {
    const v = rec.value as Record<string, number | string> | unknown;
    if (rec.key.startsWith("chunking.")) {
      const c = v as { strategy: string; size: number; overlap: number };
      return (
        <>
          {c.strategy}
          <span className="value-detail">
            {c.size} tok · {t.overlap.toLowerCase()} {c.overlap}
          </span>
        </>
      );
    }
    if (rec.key === "retrieval.top_k") {
      const k = v as { final: number; candidates: number };
      return (
        <>
          {k.final}
          {k.candidates !== k.final && <span className="value-detail">← {k.candidates}</span>}
        </>
      );
    }
    if (rec.key === "metadata") {
      return (
        <span className="chips">
          {(v as string[]).map((field) => (
            <code key={field}>{field}</code>
          ))}
        </span>
      );
    }
    if (rec.key === "embedding.dimension") {
      return (
        <>
          {String(v)}
          <span className="value-detail">{(rec.evidence.models as string[]).join(", ")}</span>
        </>
      );
    }
    if (typeof v === "boolean") return v ? t.yes : t.no;
    if (typeof v === "number") return num(v);
    return String(v);
  };
}

function Recommendations({ report }: { report: ReportData }) {
  const t = useT();
  const format = useFormatValue();
  const sections: Record<string, Recommendation[]> = {};
  const sectionOf: Record<string, string> = { vectors: "embedding", metadata: "retrieval" };
  for (const rec of report.recommendations) {
    const prefix = rec.key.split(".")[0];
    (sections[sectionOf[prefix] ?? prefix] ??= []).push(rec);
  }
  return (
    <section className="block">
      <div className="block-head">
        <h2>{t.recommendations}</h2>
        <p className="muted">
          {t.recommendationsHint} {t.reasonsNote}
        </p>
      </div>
      {Object.entries(sections).map(([section, recs]) => (
        <div key={section} className="rec-section">
          <h3 className="section-title">
            {SECTION_ICONS[section]}
            {t.sections[section] ?? section}
          </h3>
          {section === "parser" ? (
            <div className="card parser-list">
              {recs.map((rec) => (
                <div key={rec.key} className="parser-row">
                  <span className="kind">{rec.key.slice(7)}</span>
                  <strong>{String(rec.value)}</strong>
                  <span className="muted">{rec.reason}</span>
                </div>
              ))}
            </div>
          ) : (
          <div className="rec-grid">
            {recs.map((rec) => (
              <article key={rec.key} className="card rec">
                <div className="rec-label">{keyLabel(t, rec.key)}</div>
                <div className="rec-value">{format(rec)}</div>
                <p className="rec-reason">{rec.reason}</p>
              </article>
            ))}
          </div>
          )}
        </div>
      ))}
    </section>
  );
}

function Simulation({ report }: { report: ReportData }) {
  const t = useT();
  const chosen = report.recommendations.filter((r) => r.key.startsWith("chunking."));
  const groups = chosen.map((r) => r.key.split(".")[1]);
  const [group, setGroup] = useState(groups[0]);
  if (!groups.length) return null;
  const pick = chosen.find((r) => r.key === `chunking.${group}`)!.value as {
    strategy: string;
    size: number;
    overlap: number;
  };
  const rows = report.simulations
    .filter((s) => s.group === group && s.size === pick.size)
    .sort((a, b) => a.damage - b.damage || a.strategy.localeCompare(b.strategy) || a.overlap - b.overlap);
  const maxDamage = Math.max(1, ...rows.map((r) => r.damage));
  const isPick = (r: SimulationResult) => r.strategy === pick.strategy && r.overlap === pick.overlap;

  return (
    <section className="block">
      <div className="block-head row">
        <div>
          <h2>{t.simulation}</h2>
          <p className="muted">{t.simulationHint}</p>
        </div>
        {groups.length > 1 && (
          <div className="segmented" role="tablist">
            {groups.map((g) => (
              <button key={g} role="tab" aria-pressed={g === group} onClick={() => setGroup(g)}>
                {t.groups[g] ?? g}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t.strategy}</th>
              <th className="num">{t.overlap}</th>
              <th className="num">{t.chunks}</th>
              <th className="num">p50</th>
              <th className="num">p95</th>
              <th className="num">{t.sentence}</th>
              <th className="num">{t.table}</th>
              <th className="num">{t.orphan}</th>
              <th className="num">{t.tiny}</th>
              <th className="damage-col">{t.damage}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.strategy}-${r.overlap}`} className={isPick(r) ? "picked" : ""}>
                <td>
                  <span className="strategy">{r.strategy}</span>
                  {isPick(r) && <span className="badge">{t.recommended}</span>}
                </td>
                <td className="num">{r.overlap}</td>
                <td className="num">{r.chunks}</td>
                <td className="num">{r.tokens.p50}</td>
                <td className="num">{r.tokens.p95}</td>
                <td className="num">{r.sentence_cut_pct}%</td>
                <td className="num">{r.table_cut_pct}%</td>
                <td className="num">{r.orphan_heading_pct}%</td>
                <td className="num">{r.tiny_pct}%</td>
                <td className="damage-col">
                  <div className="bar">
                    <span style={{ width: `${(100 * r.damage) / maxDamage}%` }} />
                  </div>
                  <span className="num">{r.damage}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Documents({ report }: { report: ReportData }) {
  const t = useT();
  return (
    <section className="block">
      <div className="block-head">
        <h2>{t.documents}</h2>
      </div>
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t.file}</th>
              <th>{t.kind}</th>
              <th className="num">{t.pages}</th>
              <th className="num">{t.tokens}</th>
              <th>{t.lang}</th>
              <th>{t.structure}</th>
              <th className="num">{t.images}</th>
              <th className="num">{t.idsPer1k}</th>
            </tr>
          </thead>
          <tbody>
            {report.documents.map((d) => (
              <tr key={d.path}>
                <td className="path">
                  <FileText size={14} />
                  {d.path}
                </td>
                <td>
                  <span className={`kind${d.kind === "pdf_scanned" || d.error ? " warn" : ""}`}>{d.kind}</span>
                </td>
                <td className="num">{d.pages ?? ""}</td>
                <td className="num">{num(d.tokens)}</td>
                <td>{d.language ?? ""}</td>
                <td className="mono">
                  {d.headings}
                  {t.headingsShort} {d.tables}
                  {t.tablesShort} {d.list_items}
                  {t.listsShort}
                </td>
                <td className="num">{d.images}</td>
                <td className="num">{d.identifiers.per_1k_tokens}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function IndexAndCost({ report }: { report: ReportData }) {
  const t = useT();
  const dimension = report.recommendations.find((r) => r.key === "embedding.dimension")?.value;
  return (
    <section className="block two-col">
      <div>
        <div className="block-head">
          <h2>{t.index}</h2>
          <p className="muted">{t.indexHint}</p>
        </div>
        <div className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th className="num">{t.dimension}</th>
                <th className="num">float32</th>
                <th className="num">int8</th>
                <th className="num">HNSW</th>
              </tr>
            </thead>
            <tbody>
              {report.index.map((i) => (
                <tr key={i.dimension} className={i.dimension === dimension ? "picked" : ""}>
                  <td className="num">
                    {i.dimension}
                    {i.dimension === dimension && <span className="badge">{t.recommended}</span>}
                  </td>
                  <td className="num">{bytes(i.float32_bytes)}</td>
                  <td className="num">{bytes(i.int8_bytes)}</td>
                  <td className="num">{bytes(i.hnsw_overhead_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <div className="block-head">
          <h2>{t.cost}</h2>
          <p className="muted">
            {num(report.costs[0]?.tokens ?? 0)} {t.tokens.toLowerCase()}
          </p>
        </div>
        <div className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t.model}</th>
                <th className="num">{t.perMillion}</th>
                <th className="num">{t.usd}</th>
              </tr>
            </thead>
            <tbody>
              {report.costs.map((c) => (
                <tr key={c.model}>
                  <td>{c.model}</td>
                  <td className="num">{c.usd_per_million.toFixed(2)}</td>
                  <td className="num">{c.usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

async function download(report: ReportData, format: "yaml" | "json" | "md") {
  let body: string;
  if (format === "json") {
    body = JSON.stringify(report, null, 2);
  } else {
    const response = await fetch(`/api/render?format=${format}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
    });
    body = await response.text();
  }
  const name = format === "yaml" ? "ragcompass.yaml" : `ragcompass-report.${format}`;
  const url = URL.createObjectURL(new Blob([body], { type: "text/plain" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  link.click();
  URL.revokeObjectURL(url);
}

export function Report({ report }: { report: ReportData }) {
  const t = useT();
  const reset = useStore((s) => s.reset);
  const s = report.summary;
  const vectors = report.recommendations.find((r) => r.key === "vectors")?.value as number;
  const stats = [
    [t.files, `${s.analysed}/${s.files}`],
    [t.tokens, num(s.tokens)],
    [t.pages, num(s.pages)],
    [t.vectors, num(vectors ?? 0)],
    [t.languages, Object.keys(s.languages).join(", ") || "n/a"],
    [t.tokenizer, s.tokenizer],
  ];
  return (
    <div className="report">
      <div className="toolbar">
        <div className="toolbar-title">
          <Database size={18} />
          <h1>{s.root}</h1>
        </div>
        <div className="actions">
          {(["yaml", "json", "md"] as const).map((format) => (
            <button key={format} className="button" onClick={() => download(report, format)}>
              <Download size={15} />
              {format === "yaml" ? "ragcompass.yaml" : format.toUpperCase()}
            </button>
          ))}
          <button className="button ghost" onClick={reset}>
            <RotateCcw size={15} />
            {t.newAnalysis}
          </button>
        </div>
      </div>
      <div className="stats">
        {stats.map(([label, value]) => (
          <div key={label} className="card stat">
            <span className="stat-label">{label}</span>
            <span className="stat-value">{value}</span>
          </div>
        ))}
      </div>
      <Recommendations report={report} />
      <Simulation report={report} />
      <Documents report={report} />
      <IndexAndCost report={report} />
    </div>
  );
}
