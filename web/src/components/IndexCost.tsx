import { Calculator } from "lucide-react";
import { useState } from "react";
import { bytes, num, usd } from "../lib/format";
import { DIMENSIONS, HNSW_BYTES_PER_VECTOR, QUANTIZATION_BYTES, indexBytes, rec, type Quantization } from "../lib/report";
import { useT } from "../store";
import type { Report } from "../types";
import { Panel, Segmented } from "./ui";

const SCALES = ["1", "10", "100", "1000"] as const;

export function IndexCost({ report }: { report: Report }) {
  const t = useT();
  const vectors = (rec(report, "vectors")?.value as number) ?? 0;
  const recDim = (rec(report, "embedding.dimension")?.value as number | null) ?? 1024;
  const recQuant = ((rec(report, "embedding.quantization")?.value as string | null) ?? "float32") as Quantization;
  const [dimension, setDimension] = useState(String(recDim));
  const [quantization, setQuantization] = useState<Quantization>(recQuant in QUANTIZATION_BYTES ? recQuant : "float32");
  const [scale, setScale] = useState<(typeof SCALES)[number]>("1");
  const factor = Number(scale);
  const n = vectors * factor;
  const dim = Number(dimension);
  const total = indexBytes(n, dim, quantization);
  const raw = n * dim * QUANTIZATION_BYTES[quantization];
  const graph = n * HNSW_BYTES_PER_VECTOR;
  const baseline = indexBytes(n, recDim, recQuant);
  const delta = baseline ? total / baseline - 1 : 0;
  const tokens = (report.costs[0]?.tokens ?? report.summary.tokens) * factor;
  const maxUsd = Math.max(1e-9, ...report.costs.map((c) => c.usd_per_million * tokens) .map((v) => v / 1e6));

  return (
    <Panel
      id="index-cost"
      title={
        <>
          <Calculator size={15} aria-hidden /> {t.indexCost}
        </>
      }
      hint={t.indexCostHint}
    >
      <div className="calc-controls">
        <div className="field">
          <span className="field-label">{t.dimension}</span>
          <Segmented size="sm" label={t.dimension} value={dimension} onChange={setDimension} options={DIMENSIONS.map((d) => ({ value: String(d), label: d === recDim ? `${d}*` : String(d) }))} />
        </div>
        <div className="field">
          <span className="field-label">{t.quantization}</span>
          <Segmented size="sm" label={t.quantization} value={quantization} onChange={setQuantization} options={(Object.keys(QUANTIZATION_BYTES) as Quantization[]).map((q) => ({ value: q, label: q }))} />
        </div>
        <div className="field">
          <span className="field-label">{t.corpusScale}</span>
          <Segmented size="sm" label={t.corpusScale} value={scale} onChange={setScale} options={SCALES.map((s) => ({ value: s, label: `${s}×` }))} />
        </div>
      </div>
      <div className="calc-result" aria-live="polite">
        <div>
          <div className="calc-big tabular">{bytes(total)}</div>
          <div className="muted tabular">
            {num(n)} {t.vectorsLower} · {bytes(raw)} {t.rawLower} + {bytes(graph)} HNSW
          </div>
        </div>
        {Math.abs(delta) > 0.001 && (
          <span className={`delta ${delta < 0 ? "down" : "up"}`}>
            {delta > 0 ? "+" : ""}
            {(delta * 100).toFixed(0)}% {t.vsRecommended}
          </span>
        )}
      </div>
      <div className="stack-bar" aria-hidden>
        <span style={{ flexGrow: raw, background: "var(--series-1)" }} />
        <span style={{ flexGrow: graph, background: "var(--series-other)" }} />
      </div>
      <table className="cost-table">
        <thead>
          <tr>
            <th>{t.model}</th>
            <th className="num">{t.perMillion}</th>
            <th className="num">
              {t.cost} ({num(tokens)} tok)
            </th>
          </tr>
        </thead>
        <tbody>
          {report.costs.map((c) => {
            const cost = (c.usd_per_million * tokens) / 1e6;
            return (
              <tr key={c.model}>
                <td>{c.model}</td>
                <td className="num tabular">{c.usd_per_million.toFixed(2)}</td>
                <td className="num">
                  <span className="cost-cell">
                    <span className="cost-bar" style={{ width: `${(100 * cost) / maxUsd}%` }} />
                    <span className="tabular">{usd(cost)}</span>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="footnote">{t.recommendedMark}</p>
    </Panel>
  );
}
