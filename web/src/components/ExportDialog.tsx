import { Check, Copy, Download, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError, fetchExport } from "../api";
import { highlight } from "../lib/highlight";
import { useStore, useT } from "../store";
import type { ExportTarget, Loaded, Report } from "../types";
import { PreviewBadge, Skeleton } from "./ui";

const TARGETS: { id: ExportTarget; label: string; file: string }[] = [
  { id: "yaml", label: "YAML", file: "ragcompass.yaml" },
  { id: "langchain", label: "LangChain", file: "ragcompass_langchain.py" },
  { id: "llamaindex", label: "LlamaIndex", file: "ragcompass_llamaindex.py" },
  { id: "haystack", label: "Haystack", file: "ragcompass_haystack.py" },
];

export function ExportDialog({ report }: { report: Report }) {
  const t = useT();
  const { lang, exportOpen, setExportOpen, expire } = useStore();
  const ref = useRef<HTMLDialogElement>(null);
  const [target, setTarget] = useState<ExportTarget>("yaml");
  const [cache, setCache] = useState<Partial<Record<ExportTarget, Loaded<string>>>>({});
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (exportOpen && !dialog.open) dialog.showModal?.() ?? dialog.setAttribute("open", "");
    if (!exportOpen && dialog.open) dialog.close?.() ?? dialog.removeAttribute("open");
  }, [exportOpen]);

  useEffect(() => setCache({}), [report, lang]);

  useEffect(() => {
    if (!exportOpen || cache[target]) return;
    let live = true;
    setError(null);
    fetchExport(report, target, lang)
      .then((loaded) => live && setCache((c) => ({ ...c, [target]: loaded })))
      .catch((e: ApiError) => {
        if (!live) return;
        if (e.expired) {
          setExportOpen(false);
          expire();
        } else setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [exportOpen, target, cache, report, lang, setExportOpen, expire]);

  const current = cache[target];
  const meta = TARGETS.find((x) => x.id === target)!;
  const copy = async () => {
    if (!current) return;
    try {
      await navigator.clipboard.writeText(current.data);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked: the text stays selectable */
    }
  };
  const download = () => {
    if (!current) return;
    const url = URL.createObjectURL(new Blob([current.data], { type: "text/plain" }));
    Object.assign(document.createElement("a"), { href: url, download: meta.file }).click();
    URL.revokeObjectURL(url);
  };
  const onTabKey = (e: React.KeyboardEvent) => {
    const i = TARGETS.findIndex((x) => x.id === target);
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
    if (next === null) return;
    const id = TARGETS[(next + TARGETS.length) % TARGETS.length].id;
    setTarget(id);
    document.getElementById(`export-tab-${id}`)?.focus();
  };

  return (
    <dialog ref={ref} className="dialog" aria-labelledby="export-title" onClose={() => setExportOpen(false)} onClick={(e) => e.target === ref.current && setExportOpen(false)}>
      <div className="dialog-body">
        <header className="dialog-head">
          <div>
            <h2 id="export-title">{t.exportTitle}</h2>
            <p className="panel-hint">{t.exportHint}</p>
          </div>
          <button className="icon-button" onClick={() => setExportOpen(false)} aria-label={t.close}>
            <X size={16} />
          </button>
        </header>
        <div className="dialog-tabs" role="tablist" aria-label={t.exportTitle} onKeyDown={onTabKey}>
          {TARGETS.map((x) => (
            <button
              key={x.id}
              id={`export-tab-${x.id}`}
              role="tab"
              aria-selected={x.id === target}
              aria-controls="export-panel"
              tabIndex={x.id === target ? 0 : -1}
              onClick={() => setTarget(x.id)}
            >
              {x.label}
            </button>
          ))}
        </div>
        <div id="export-panel" role="tabpanel" aria-labelledby={`export-tab-${target}`} className="code-panel">
          <div className="code-bar">
            <span className="mono muted">{meta.file}</span>
            {current?.preview && <PreviewBadge />}
            <span className="spacer" />
            <button className="button sm" onClick={copy} disabled={!current}>
              {copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
              {copied ? t.copied : t.copy}
            </button>
            <button className="button sm" onClick={download} disabled={!current}>
              <Download size={14} aria-hidden />
              {t.download}
            </button>
          </div>
          {error ? (
            <p className="inline-error" role="alert">
              {error}
            </p>
          ) : current ? (
            <pre className="code" tabIndex={0}>
              <code>
                {highlight(current.data, target === "yaml" ? "yaml" : "python").map((tok, i) =>
                  tok.kind === "plain" ? tok.text : (
                    <span key={i} className={`tok-${tok.kind}`}>
                      {tok.text}
                    </span>
                  ),
                )}
              </code>
            </pre>
          ) : (
            <div className="code">
              {Array.from({ length: 12 }, (_, i) => (
                <Skeleton key={i} h={12} w={`${40 + ((i * 29) % 50)}%`} />
              ))}
            </div>
          )}
          <span className="sr-only" aria-live="polite">
            {copied ? t.copied : ""}
          </span>
        </div>
      </div>
    </dialog>
  );
}
