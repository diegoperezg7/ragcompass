import { FileUp, FolderUp, Play, TriangleAlert, UploadCloud } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { bytes } from "../lib/format";
import { MAX_FILES, MAX_UPLOAD_MB, useStore, useT } from "../store";
import { DashboardSkeleton } from "./Skeletons";

// Folder drops arrive as directory entries; walk them and keep relative paths.
async function readEntry(entry: FileSystemEntry, prefix = ""): Promise<File[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject));
    return [new File([file], prefix + file.name, { type: file.type })];
  }
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  const children: FileSystemEntry[] = [];
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) break;
    children.push(...batch);
  }
  const nested = await Promise.all(children.map((child) => readEntry(child, `${prefix}${entry.name}/`)));
  return nested.flat();
}

const SAMPLE_KINDS = ["PDF", "scanned PDF", "DOCX", "Markdown", "HTML", "CSV", "XLSX", "Python", "PNG"];

function Progress() {
  const t = useT();
  const { status, progress, upload } = useStore();
  const uploading = status === "uploading";
  return (
    <div className="progress-card" role="status" aria-live="polite">
      <div className="progress-head">
        <span className="pulse-dot" aria-hidden />
        <strong>{uploading ? t.uploading : t.analysing}</strong>
        <span className="muted tabular">
          {uploading && upload
            ? `${bytes(upload.bytes * progress)} / ${bytes(upload.bytes)} · ${Math.round(progress * 100)}%`
            : t.analysingHint}
        </span>
      </div>
      <div
        className={`progress-bar${uploading ? "" : " indeterminate"}`}
        role="progressbar"
        aria-label={uploading ? t.uploading : t.analysing}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={uploading ? Math.round(progress * 100) : undefined}
      >
        <span style={uploading ? { width: `${progress * 100}%` } : undefined} />
      </div>
    </div>
  );
}

function ErrorBox() {
  const t = useT();
  const { error, reset } = useStore();
  if (!error) return null;
  const copy = t.errors[error.code];
  return (
    <div className="alert" role="alert">
      <TriangleAlert size={18} aria-hidden />
      <div>
        <strong>{copy.title}</strong>
        <p>{copy.hint.replace("{max}", String(error.code === "tooMany" ? MAX_FILES : MAX_UPLOAD_MB))}</p>
        {error.detail && error.code === "server" && <code className="alert-detail">{error.detail}</code>}
      </div>
      <button className="button sm" onClick={reset}>
        {t.dismiss}
      </button>
    </div>
  );
}

export function Home() {
  const t = useT();
  const { status, analyseFiles, analyseSample } = useStore();
  const [dragging, setDragging] = useState(false);
  const filesInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const busy = status === "uploading" || status === "analysing";

  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
  }, []);

  const onDrop = async (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    const entries = Array.from(event.dataTransfer.items)
      .map((item) => item.webkitGetAsEntry())
      .filter((entry): entry is FileSystemEntry => entry !== null);
    analyseFiles((await Promise.all(entries.map((entry) => readEntry(entry)))).flat());
  };

  const onPick = (input: HTMLInputElement | null) => {
    const files = Array.from(input?.files ?? []);
    if (files.length) analyseFiles(files);
    if (input) input.value = "";
  };

  return (
    <div className="home">
      <div className="home-intro">
        <h1>{t.homeTitle}</h1>
        <p className="muted">{t.tagline}</p>
      </div>
      <div className="home-grid">
        <section
          className={`dropzone${dragging ? " dragging" : ""}${busy ? " busy" : ""}`}
          aria-label={t.dropTitle}
          onDragOver={(event) => {
            event.preventDefault();
            if (!busy) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          {busy ? (
            <Progress />
          ) : (
            <>
              <div className="dropzone-icon" aria-hidden>
                <UploadCloud size={22} />
              </div>
              <h2>{t.dropTitle}</h2>
              <p className="muted">{t.dropHint}</p>
              <div className="actions">
                <button className="button primary" onClick={() => filesInput.current?.click()}>
                  <FileUp size={16} aria-hidden />
                  {t.chooseFiles}
                </button>
                <button className="button" onClick={() => folderInput.current?.click()}>
                  <FolderUp size={16} aria-hidden />
                  {t.chooseFolder}
                </button>
              </div>
              <p className="limits">{t.limits.replace("{files}", String(MAX_FILES)).replace("{mb}", String(MAX_UPLOAD_MB))}</p>
            </>
          )}
          <input ref={filesInput} type="file" multiple hidden onChange={(e) => onPick(e.currentTarget)} />
          <input ref={folderInput} type="file" multiple hidden onChange={(e) => onPick(e.currentTarget)} />
        </section>
        <aside className="sample-card">
          <div className="sample-head">
            <span className="eyebrow">{t.sampleEyebrow}</span>
            <h2>{t.sampleTitle}</h2>
            <p className="muted">{t.sampleHint}</p>
          </div>
          <ul className="sample-kinds" aria-label={t.sampleTitle}>
            {SAMPLE_KINDS.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
          <button className="button primary block" onClick={analyseSample} disabled={busy}>
            <Play size={15} aria-hidden />
            {t.trySample}
          </button>
        </aside>
      </div>
      {status === "error" && <ErrorBox />}
      {status === "analysing" && <DashboardSkeleton />}
    </div>
  );
}
