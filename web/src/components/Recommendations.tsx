import { Binary, Blocks, ChevronDown, Layers, ScanSearch, ScanText, Search, Tags } from "lucide-react";
import { useState, type ReactNode } from "react";
import { keyLabel } from "../i18n";
import { bytes, num } from "../lib/format";
import { groupOf } from "../lib/report";
import { useStore, useT } from "../store";
import type { Recommendation, Report } from "../types";
import { BasisBadge, Panel } from "./ui";

const SECTION_ICONS: Record<string, ReactNode> = {
  parser: <ScanText size={14} />,
  chunking: <Blocks size={14} />,
  embedding: <Binary size={14} />,
  retrieval: <Search size={14} />,
};
const SECTION_OF: Record<string, string> = { vectors: "embedding", metadata: "retrieval" };

function useReason() {
  const lang = useStore((s) => s.lang);
  return (r: Recommendation) => r.reason_i18n?.[lang] ?? r.reason;
}

function Value({ r }: { r: Recommendation }) {
  const t = useT();
  const v = r.value;
  if (v === null || v === undefined) return <span className="undecided">{t.undecided}</span>;
  if (r.key.startsWith("chunking.")) {
    const c = v as { strategy: string; size: number; overlap: number };
    return (
      <>
        {c.strategy}
        <span className="value-detail">
          {c.size} tok · {t.overlapLower} {c.overlap}
        </span>
      </>
    );
  }
  if (r.key === "retrieval.top_k") {
    const k = v as { final: number; candidates: number };
    return (
      <>
        {k.final}
        {k.candidates !== k.final && (
          <span className="value-detail">
            {t.fromCandidates} {k.candidates}
          </span>
        )}
      </>
    );
  }
  if (r.key === "metadata") {
    return (
      <span className="chips">
        {(v as string[]).map((field) => (
          <code key={field}>{field}</code>
        ))}
      </span>
    );
  }
  if (typeof v === "boolean") return <>{v ? t.yes : t.no}</>;
  if (typeof v === "number") return <>{num(v)}</>;
  return <>{String(v)}</>;
}

function evidenceValue(key: string, value: unknown): string {
  if (typeof value === "number") return key.endsWith("bytes") ? bytes(value) : num(value);
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object")
    return Object.entries(value)
      .map(([k, v]) => `${k} ${typeof v === "number" ? num(v) : String(v)}`)
      .join(" · ");
  return String(value);
}

function Card({ r, report }: { r: Recommendation; report: Report }) {
  const t = useT();
  const reason = useReason();
  const openExplorer = useStore((s) => s.openExplorer);
  const [open, setOpen] = useState(false);
  const basis = r.basis ?? "rule-based";
  const evidence = Object.entries(r.evidence ?? {});
  const id = `rec-${r.key.replace(/\W/g, "-")}`;
  const chunk = r.key.startsWith("chunking.") ? (r.value as { strategy: string; size: number; overlap: number } | null) : null;
  const baseline = r.evidence?.fixed_baseline_damage as number | undefined;
  const damage = r.evidence?.damage as number | undefined;
  const sample = chunk
    ? [...report.documents].filter((d) => d.tokens > 0 && groupOf(d.kind) === r.key.slice(9)).sort((a, b) => b.tokens - a.tokens)[0]
    : undefined;
  return (
    <article className={`rec-card${open ? " open" : ""}`}>
      <div className="rec-top">
        <span className="rec-label">{keyLabel(t, r.key)}</span>
        <BasisBadge basis={basis} />
      </div>
      <div className="rec-value">
        <Value r={r} />
      </div>
      {baseline !== undefined && damage !== undefined && baseline > 0 && (
        <div className="rec-delta">
          <span className="delta-good">−{Math.round(100 - (100 * damage) / baseline)}%</span> {t.damageVsFixed}
        </div>
      )}
      <button className="rec-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        {t.why}
        <ChevronDown size={14} aria-hidden />
      </button>
      <div id={id} className="rec-more" hidden={!open}>
        <p className="rec-reason">{reason(r)}</p>
        {evidence.length > 0 && (
          <dl className="evidence">
            {evidence.map(([k, v]) => (
              <div key={k}>
                <dt>{k.replace(/_/g, " ")}</dt>
                <dd>{evidenceValue(k, v)}</dd>
              </div>
            ))}
          </dl>
        )}
        {chunk && sample && (
          <button className="link-button" onClick={() => openExplorer({ file: sample.path, ...chunk })}>
            <ScanSearch size={13} aria-hidden /> {t.seeInExplorer}
          </button>
        )}
      </div>
    </article>
  );
}

export function Recommendations({ report }: { report: Report }) {
  const t = useT();
  const reason = useReason();
  const sections: Record<string, Recommendation[]> = {};
  for (const r of report.recommendations) {
    const prefix = r.key.split(".")[0];
    (sections[SECTION_OF[prefix] ?? prefix] ??= []).push(r);
  }
  const parsers = sections.parser ?? [];
  delete sections.parser;
  return (
    <Panel id="recommendations" title={t.recommendations} hint={t.recommendationsHint} className="span-3 flush">
      <div className="rec-sections">
        {Object.entries(sections).map(([section, recs]) => (
          <div key={section} className="rec-section">
            <h3 className="section-title">
              {SECTION_ICONS[section] ?? <Layers size={14} />}
              {t.sections[section] ?? section}
            </h3>
            <div className="rec-grid">
              {recs.map((r) => (
                <Card key={r.key} r={r} report={report} />
              ))}
            </div>
          </div>
        ))}
        {parsers.length > 0 && (
          <div className="rec-section">
            <h3 className="section-title">
              {SECTION_ICONS.parser}
              {t.sections.parser}
            </h3>
            <div className="parser-list">
              {parsers.map((r) => (
                <div key={r.key} className="parser-row">
                  <span className="kind-chip">{r.key.slice(7)}</span>
                  <strong>{String(r.value)}</strong>
                  <span className="muted">{reason(r)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <p className="footnote">
        <Tags size={12} aria-hidden /> {t.basisFootnote}
      </p>
    </Panel>
  );
}
