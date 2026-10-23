import { FileUp, FolderUp, Loader2, Sparkles, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { useStore, useT } from "../store";

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

export function Upload() {
  const t = useT();
  const { status, error, analyseFiles, analyseSample } = useStore();
  const [dragging, setDragging] = useState(false);
  const filesInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
  }, []);

  const onDrop = async (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const entries = Array.from(event.dataTransfer.items)
      .map((item) => item.webkitGetAsEntry())
      .filter((entry): entry is FileSystemEntry => entry !== null);
    const files = (await Promise.all(entries.map((entry) => readEntry(entry)))).flat();
    if (files.length) analyseFiles(files);
  };

  const onPick = (input: HTMLInputElement | null) => {
    const files = Array.from(input?.files ?? []);
    if (files.length) analyseFiles(files);
    if (input) input.value = "";
  };

  if (status === "loading") {
    return (
      <section className="card dropzone loading" aria-live="polite">
        <Loader2 className="spin" size={28} />
        <h2>{t.analysing}</h2>
        <p className="muted">{t.analysingHint}</p>
      </section>
    );
  }

  return (
    <>
      <section
        className={`card dropzone${dragging ? " dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <div className="dropzone-icon">
          <FolderUp size={26} />
        </div>
        <h2>{t.dropTitle}</h2>
        <p className="muted">{t.dropHint}</p>
        <div className="actions">
          <button className="button primary" onClick={() => filesInput.current?.click()}>
            <FileUp size={16} />
            {t.chooseFiles}
          </button>
          <button className="button" onClick={() => folderInput.current?.click()}>
            <FolderUp size={16} />
            {t.chooseFolder}
          </button>
          <button className="button ghost" onClick={analyseSample}>
            <Sparkles size={16} />
            {t.trySample}
          </button>
        </div>
        <input ref={filesInput} type="file" multiple hidden onChange={(e) => onPick(e.currentTarget)} />
        <input ref={folderInput} type="file" multiple hidden onChange={(e) => onPick(e.currentTarget)} />
      </section>
      {status === "error" && (
        <div className="card alert" role="alert">
          <TriangleAlert size={18} />
          <div>
            <strong>{t.errorTitle}</strong>
            <p className="muted">{error}</p>
          </div>
        </div>
      )}
    </>
  );
}
