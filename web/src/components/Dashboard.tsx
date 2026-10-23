import { FileText, TriangleAlert } from "lucide-react";
import { num } from "../lib/format";
import { groupOf } from "../lib/report";
import { useStore, useT } from "../store";
import type { Report } from "../types";
import { Benchmark } from "./Benchmark";
import { Chunking } from "./Chunking";
import { Composition, CorpusMap } from "./CorpusMap";
import { IndexCost } from "./IndexCost";
import { Overview, Pipeline } from "./Overview";
import { Projection } from "./Projection";
import { Recommendations } from "./Recommendations";
import { Panel } from "./ui";

function Documents({ report }: { report: Report }) {
  const t = useT();
  const openExplorer = useStore((s) => s.openExplorer);
  const docs = [...report.documents].sort((a, b) => b.tokens - a.tokens);
  const max = Math.max(1, ...docs.map((d) => d.tokens));
  return (
    <Panel id="documents" title={t.documents} hint={`${docs.length} ${t.filesLower}`} className="span-3 flush">
      <div className="table-wrap">
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
            {docs.map((d) => {
              const explorable = d.tokens > 0 && groupOf(d.kind) !== null;
              const warnings = [...(d.error ? [d.error] : []), ...(d.warnings ?? [])];
              return (
                <tr key={d.path}>
                  <td>
                    {explorable ? (
                      <button className="path link" onClick={() => openExplorer({ file: d.path })} title={t.clickToExplore}>
                        <FileText size={14} aria-hidden />
                        {d.path}
                      </button>
                    ) : (
                      <span className="path">
                        <FileText size={14} aria-hidden />
                        {d.path}
                      </span>
                    )}
                    {warnings.length > 0 && (
                      <span className="row-warn" title={warnings.join("\n")}>
                        <TriangleAlert size={13} aria-label={t.warnings} />
                      </span>
                    )}
                  </td>
                  <td>
                    <span className={`kind-chip${d.kind === "pdf_scanned" || d.kind === "image" ? " warn" : ""}${d.error ? " error" : ""}`}>{d.kind}</span>
                  </td>
                  <td className="num tabular">{d.pages ?? "–"}</td>
                  <td className="num">
                    <span className="cell-bar">
                      <span style={{ width: `${(100 * d.tokens) / max}%` }} />
                      <span className="tabular">{num(d.tokens)}</span>
                    </span>
                  </td>
                  <td>{d.language ?? "–"}</td>
                  <td className="mono small">
                    {d.headings}
                    {t.headingsShort} · {d.tables}
                    {t.tablesShort} · {d.list_items}
                    {t.listsShort}
                  </td>
                  <td className="num tabular">{d.images}</td>
                  <td className="num tabular">{d.identifiers.per_1k_tokens}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export function Dashboard({ report }: { report: Report }) {
  return (
    <div className="dashboard">
      <Pipeline report={report} />
      <Overview report={report} />
      <div className="grid three">
        <CorpusMap report={report} />
        <Composition report={report} />
        <Recommendations report={report} />
        <Chunking report={report} />
        <Benchmark />
        <Projection report={report} />
        <IndexCost report={report} />
        <Documents report={report} />
      </div>
    </div>
  );
}
