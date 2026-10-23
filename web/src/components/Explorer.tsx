import { ArrowDown, ArrowUp, Columns2, RotateCcw, ScanSearch, Scissors, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, fetchChunks, type ChunkQuery } from "../api";
import { num } from "../lib/format";
import { groupOf, picks } from "../lib/report";
import { useStore, useT } from "../store";
import type { ChunkSpan, ChunkView, Report } from "../types";
import { STRATEGY_SLOT } from "./Chunking";
import { TextSkeleton } from "./Skeletons";
import { Empty, Segmented } from "./ui";

const STRATEGIES: Record<string, string[]> = {
  documents: ["heading", "page", "recursive", "fixed"],
  tables: ["row", "recursive", "fixed"],
  code: ["recursive", "fixed"],
};
const NO_OVERLAP = new Set(["heading", "page", "row"]);
const DEBOUNCE_MS = 250;

interface Config {
  strategy: string;
  size: number;
  overlap: number;
}

function useChunks(report: Report, file: string, config: Config) {
  const expire = useStore((s) => s.expire);
  const [state, setState] = useState<{ view: ChunkView | null; loading: boolean; error: string | null }>({ view: null, loading: true, error: null });
  useEffect(() => {
    if (!file) return;
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    const timer = setTimeout(() => {
      fetchChunks(report, { file, ...config }, controller.signal)
        .then((view) => setState({ view, loading: false, error: null }))
        .catch((error: ApiError) => {
          if (error.name === "AbortError") return;
          if (error.expired) return expire();
          setState((s) => ({ ...s, loading: false, error: error.message }));
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [report, file, config.strategy, config.size, config.overlap, expire]);
  return state;
}

const damaged = (c: ChunkSpan) => c.issues.some((i) => i.kind !== "tiny");

function Minimap({ view, current, onPick }: { view: ChunkView; current: number; onPick: (i: number) => void }) {
  const t = useT();
  const length = Math.max(1, view.text.length);
  return (
    <div className="minimap" role="group" aria-label={t.minimap}>
      {view.chunks.map((c, i) => {
        // Each chunk owns the text up to where the next one starts, so overlapping chunks do not stack.
        const end = Math.max(c.start + 1, Math.min(c.end, view.chunks[i + 1]?.start ?? c.end));
        return (
          <button
            key={c.index}
            className={`mm-seg${damaged(c) ? " bad" : c.issues.length ? " tiny" : ""}${i === current ? " current" : ""}${i % 2 ? " odd" : ""}`}
            style={{ left: `${(100 * c.start) / length}%`, width: `${(100 * (end - c.start)) / length}%` }}
            onClick={() => onPick(i)}
            aria-label={`${t.chunk} ${i + 1}${damaged(c) ? `, ${t.damaged}` : ""}`}
            title={`#${i + 1} · ${c.tokens} tok${c.issues.length ? " · " + c.issues.map((x) => t.issues[x.kind]).join(", ") : ""}`}
          />
        );
      })}
    </div>
  );
}

function ChunkBlock({ view, chunk, previousEnd, selected, onSelect }: { view: ChunkView; chunk: ChunkSpan; previousEnd: number; selected: boolean; onSelect: () => void }) {
  const t = useT();
  const overlapEnd = Math.min(chunk.end, Math.max(chunk.start, previousEnd));
  const cut = chunk.boundaries.end !== "clean";
  return (
    <div
      className={`chunk${selected ? " selected" : ""}${damaged(chunk) ? " bad" : ""}`}
      data-index={chunk.index}
      onClick={onSelect}
    >
      <div className="chunk-head">
        <span className="chunk-id">#{chunk.index + 1}</span>
        <span className="tabular muted">
          {chunk.tokens} tok{chunk.extra_tokens ? ` (+${chunk.extra_tokens} ${t.header})` : ""}
        </span>
        {chunk.issues.map((issue, i) => (
          <span key={i} className={`issue ${issue.kind === "tiny" ? "minor" : ""}`} title={issue.detail}>
            {issue.kind !== "tiny" && <TriangleAlert size={11} aria-hidden />}
            {t.issues[issue.kind]}
          </span>
        ))}
      </div>
      <div className="chunk-text">
        {overlapEnd > chunk.start && (
          <span className="overlap" title={t.overlapText}>
            {view.text.slice(chunk.start, overlapEnd)}
          </span>
        )}
        {view.text.slice(overlapEnd, chunk.end)}
      </div>
      {cut && (
        <div className="cut-mark">
          <Scissors size={12} aria-hidden />
          {t.boundaries[chunk.boundaries.end]}
          {chunk.issues.find((i) => i.kind !== "tiny" && i.detail) && <span className="cut-detail">{chunk.issues.find((i) => i.kind !== "tiny")?.detail}</span>}
        </div>
      )}
    </div>
  );
}

function Pane({
  report,
  file,
  group,
  config,
  setConfig,
  recommended,
  focus,
  label,
}: {
  report: Report;
  file: string;
  group: string;
  config: Config;
  setConfig: (c: Config) => void;
  recommended: Config | undefined;
  focus?: number;
  label?: string;
}) {
  const t = useT();
  const { view, loading, error } = useChunks(report, file, config);
  const [current, setCurrent] = useState(focus ?? 0);
  const textRef = useRef<HTMLDivElement>(null);
  const strategies = view?.strategies ?? STRATEGIES[group] ?? ["recursive", "fixed"];
  const chunks = view?.chunks ?? [];
  const isRecommended = recommended && config.strategy === recommended.strategy && config.size === recommended.size && config.overlap === recommended.overlap;
  const overlapPct = config.size ? Math.round((100 * config.overlap) / config.size) : 0;

  useEffect(() => {
    setCurrent((c) => Math.min(c, Math.max(0, chunks.length - 1)));
  }, [chunks.length]);

  const go = (index: number) => {
    const i = Math.max(0, Math.min(chunks.length - 1, index));
    setCurrent(i);
    textRef.current?.querySelector(`[data-index="${chunks[i]?.index}"]`)?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  };
  const nextIssue = (direction: 1 | -1) => {
    for (let step = 1; step <= chunks.length; step++) {
      const i = (current + direction * step + chunks.length) % chunks.length;
      if (damaged(chunks[i])) return go(i);
    }
  };

  useEffect(() => {
    if (focus !== undefined && view) go(focus);
  }, [focus, view?.file]);

  const bad = chunks.filter(damaged).length;
  return (
    <section className="pane" aria-label={label ?? t.explorer}>
      <div className="pane-controls">
        {label && <span className="pane-label">{label}</span>}
        <Segmented
          size="sm"
          label={t.strategy}
          value={config.strategy}
          onChange={(strategy) => setConfig({ ...config, strategy, overlap: NO_OVERLAP.has(strategy) ? 0 : config.overlap })}
          options={strategies.map((s) => ({
            value: s,
            label: (
              <>
                <span className="swatch round" style={{ background: `var(--series-${STRATEGY_SLOT[s] ?? 6})` }} />
                {s}
              </>
            ),
          }))}
        />
        <label className="slider">
          <span>
            {t.size} <strong className="tabular">{config.size}</strong>
          </span>
          <input type="range" min={64} max={2048} step={32} value={config.size} onChange={(e) => setConfig({ ...config, size: Number(e.target.value), overlap: Math.round((Number(e.target.value) * overlapPct) / 100) })} />
        </label>
        <label className={`slider${NO_OVERLAP.has(config.strategy) ? " disabled" : ""}`} title={NO_OVERLAP.has(config.strategy) ? t.noOverlapHint : undefined}>
          <span>
            {t.overlap} <strong className="tabular">{overlapPct}%</strong>
          </span>
          <input
            type="range"
            min={0}
            max={50}
            step={5}
            value={overlapPct}
            disabled={NO_OVERLAP.has(config.strategy)}
            onChange={(e) => setConfig({ ...config, overlap: Math.round((config.size * Number(e.target.value)) / 100) })}
          />
        </label>
        {recommended && !isRecommended && (
          <button className="button sm ghost" onClick={() => setConfig(recommended)} title={t.backToRecommended}>
            <RotateCcw size={14} aria-hidden />
            <span className="hide-sm">{t.recommended}</span>
          </button>
        )}
        {isRecommended && <span className="badge accent">{t.recommended}</span>}
      </div>
      {error ? (
        <div className="alert" role="alert">
          <TriangleAlert size={16} aria-hidden />
          <div>
            <strong>{t.chunksFailed}</strong>
            <p>{error}</p>
          </div>
        </div>
      ) : !view ? (
        <TextSkeleton />
      ) : (
        <>
          <div className="pane-stats" aria-live="polite">
            <span>
              <strong className="tabular">{num(chunks.length)}</strong> {t.chunksLower}
            </span>
            <span className={bad ? "stat-bad" : ""}>
              <strong className="tabular">{bad}</strong> {t.damagedLower}
            </span>
            <span>
              {t.damage} <strong className="tabular">{view.metrics.damage.toFixed(1)}</strong>
            </span>
            <span>
              p50 <strong className="tabular">{view.metrics.tokens.p50}</strong>
            </span>
            {view.applied_strategy !== view.strategy && <span className="note">{t.fellBack.replace("{s}", view.applied_strategy)}</span>}
            {loading && <span className="pulse-dot" aria-label={t.loading} />}
          </div>
          <Minimap view={view} current={current} onPick={go} />
          <div className="pane-nav">
            <button className="icon-button sm" onClick={() => go(current - 1)} disabled={current === 0} aria-label={t.prevChunk}>
              <ArrowUp size={15} />
            </button>
            <span className="tabular">
              {t.chunk} {Math.min(current + 1, chunks.length)} / {chunks.length}
            </span>
            <button className="icon-button sm" onClick={() => go(current + 1)} disabled={current >= chunks.length - 1} aria-label={t.nextChunk}>
              <ArrowDown size={15} />
            </button>
            <button className="button sm ghost" onClick={() => nextIssue(1)} disabled={!bad}>
              <TriangleAlert size={13} aria-hidden /> {t.nextIssue}
            </button>
            <span className="kbd-hint hide-sm">
              <kbd>j</kbd> <kbd>k</kbd> {t.navigate} · <kbd>n</kbd> {t.nextIssueLower}
            </span>
          </div>
          <div
            ref={textRef}
            className={`chunk-list${loading ? " stale" : ""}`}
            tabIndex={0}
            aria-label={t.chunkText}
            onKeyDown={(e) => {
              if (e.key === "j" || e.key === "ArrowDown") (e.preventDefault(), go(current + 1));
              else if (e.key === "k" || e.key === "ArrowUp") (e.preventDefault(), go(current - 1));
              else if (e.key === "n") nextIssue(1);
              else if (e.key === "N") nextIssue(-1);
            }}
          >
            {chunks.map((c, i) => (
              <ChunkBlock key={c.index} view={view} chunk={c} previousEnd={i ? chunks[i - 1].end : 0} selected={i === current} onSelect={() => setCurrent(i)} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

export function Explorer({ report }: { report: Report }) {
  const t = useT();
  const { explore, openExplorer } = useStore();
  const docs = useMemo(() => report.documents.filter((d) => d.tokens > 0 && groupOf(d.kind) !== null).sort((a, b) => b.tokens - a.tokens), [report]);
  const chosen = picks(report);
  // Prose shows chunk boundaries best, so a document opens first unless a file was asked for.
  const fallback = docs.find((d) => groupOf(d.kind) === "documents") ?? docs[0];
  const file = explore?.file && docs.some((d) => d.path === explore.file) ? explore.file : fallback?.path ?? "";
  const doc = docs.find((d) => d.path === file);
  const group = doc ? (groupOf(doc.kind) ?? "documents") : "documents";
  const recommended = chosen[group];
  const initial = (q: ChunkQuery | null): Config => ({
    strategy: q?.strategy ?? recommended?.strategy ?? "recursive",
    size: q?.size ?? recommended?.size ?? 512,
    overlap: q?.overlap ?? recommended?.overlap ?? 0,
  });
  const [a, setA] = useState<Config>(() => initial(explore));
  const [b, setB] = useState<Config>(() => ({ strategy: "fixed", size: initial(explore).size, overlap: 0 }));
  const [compare, setCompare] = useState(false);

  // Opening the explorer from a chart or the corpus map carries a configuration with it.
  useEffect(() => {
    if (explore) setA(initial(explore));
  }, [explore]);

  if (!docs.length) {
    return (
      <div className="explorer">
        <Empty icon={<ScanSearch size={20} />} title={t.noExplorable}>
          <p>{t.noExplorableHint}</p>
        </Empty>
      </div>
    );
  }

  return (
    <div className="explorer">
      <div className="explorer-bar">
        <div className="field">
          <label htmlFor="explorer-file" className="field-label">
            {t.file}
          </label>
          <select
            id="explorer-file"
            className="select"
            value={file}
            onChange={(e) => {
              const next = docs.find((d) => d.path === e.target.value);
              const g = next ? groupOf(next.kind) ?? "documents" : group;
              openExplorer({ file: e.target.value, ...(chosen[g] ?? {}) });
            }}
          >
            {docs.map((d) => (
              <option key={d.path} value={d.path}>
                {d.path} · {d.kind} · {num(d.tokens)} tok
              </option>
            ))}
          </select>
        </div>
        <button className={`button sm${compare ? " active" : ""}`} aria-pressed={compare} onClick={() => setCompare(!compare)}>
          <Columns2 size={15} aria-hidden />
          {t.compare}
        </button>
      </div>
      <div className={`panes${compare ? " split" : ""}`}>
        <Pane key={`a-${file}`} report={report} file={file} group={group} config={a} setConfig={setA} recommended={recommended} focus={explore?.focus} label={compare ? "A" : undefined} />
        {compare && <Pane key={`b-${file}`} report={report} file={file} group={group} config={b} setConfig={setB} recommended={recommended} label="B" />}
      </div>
    </div>
  );
}
