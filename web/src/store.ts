import { create } from "zustand";
import { ApiError, fetchReport, postWithProgress, runBench, type ChunkQuery } from "./api";
import { dictionaries, type Lang } from "./i18n";
import type { Bench, Report } from "./types";

type Theme = "light" | "dark";
export type Status = "idle" | "uploading" | "analysing" | "done" | "error";
export type View = "report" | "explorer";

export const MAX_FILES = 500;
export const MAX_UPLOAD_MB = 50;

export interface AppError {
  code: "tooMany" | "tooLarge" | "empty" | "network" | "server" | "expired";
  detail?: string;
}

interface State {
  lang: Lang;
  theme: Theme;
  status: Status;
  progress: number;
  upload: { files: number; bytes: number } | null;
  report: Report | null;
  error: AppError | null;
  view: View;
  explore: ChunkQuery | null;
  exportOpen: boolean;
  bench: { data: Bench; preview: boolean } | null;
  benchState: "idle" | "running" | "error";
  benchError: string | null;
  runBench: () => Promise<void>;
  /** The server forgot the report: go back to the upload screen and say why. */
  expire: () => void;
  setLang: (lang: Lang) => void;
  toggleTheme: () => void;
  analyseFiles: (files: File[]) => Promise<void>;
  analyseSample: () => Promise<void>;
  setView: (view: View) => void;
  openExplorer: (query: ChunkQuery) => void;
  setExportOpen: (open: boolean) => void;
  reset: () => void;
}

function stored<T extends string>(key: string, allowed: readonly T[]): T | null {
  try {
    const value = localStorage.getItem(key);
    return allowed.includes(value as T) ? (value as T) : null;
  } catch {
    return null;
  }
}

function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: keep the choice for this session only */
  }
}

const prefersDark = typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
const initialTheme: Theme = stored("ragcompass.theme", ["light", "dark"] as const) ?? (prefersDark ? "dark" : "light");
const initialLang: Lang =
  stored("ragcompass.lang", ["en", "es"] as const) ?? (navigator.language.startsWith("es") ? "es" : "en");

document.documentElement.dataset.theme = initialTheme;
document.documentElement.lang = initialLang;

function toAppError(error: unknown): AppError {
  if (error instanceof ApiError) {
    if (error.status === 413) return { code: "tooLarge", detail: error.message };
    if (error.status === 0) return { code: "network" };
    return { code: "server", detail: error.message };
  }
  return { code: "server", detail: (error as Error).message };
}

const loaded = (report: Report) => ({
  report,
  status: "done" as const,
  view: "report" as const,
  explore: null,
  bench: report.bench ? { data: report.bench, preview: false } : null,
  benchState: "idle" as const,
});

export const useStore = create<State>((set, get) => ({
  lang: initialLang,
  theme: initialTheme,
  status: "idle",
  progress: 0,
  upload: null,
  report: null,
  error: null,
  view: "report",
  explore: null,
  exportOpen: false,
  bench: null,
  benchState: "idle",
  benchError: null,
  runBench: async () => {
    const report = get().report;
    if (!report) return;
    set({ benchState: "running", benchError: null });
    try {
      const bench = await runBench(report, get().lang);
      if (get().report !== report) return;
      const updated = bench.preview ? report : await fetchReport(report, get().lang).catch(() => report);
      set({ bench, benchState: "idle", report: updated });
    } catch (error) {
      if ((error as ApiError).expired) return get().expire();
      set({ benchState: "error", benchError: (error as Error).message });
    }
  },
  setLang: (lang) => {
    save("ragcompass.lang", lang);
    document.documentElement.lang = lang;
    set({ lang });
  },
  toggleTheme: () => {
    const theme = get().theme === "dark" ? "light" : "dark";
    save("ragcompass.theme", theme);
    document.documentElement.dataset.theme = theme;
    set({ theme });
  },
  analyseFiles: async (files) => {
    const bytes = files.reduce((sum, f) => sum + f.size, 0);
    if (!files.length) return set({ status: "error", error: { code: "empty" } });
    if (files.length > MAX_FILES) return set({ status: "error", error: { code: "tooMany", detail: String(files.length) } });
    if (bytes > MAX_UPLOAD_MB * 1024 * 1024) return set({ status: "error", error: { code: "tooLarge" } });
    const form = new FormData();
    const names = files.map((file) => (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name);
    files.forEach((file, i) => form.append("files", file, names[i]));
    set({ status: "uploading", progress: 0, upload: { files: files.length, bytes }, error: null });
    try {
      const report = await postWithProgress("/api/analyze?lang=" + get().lang, form, (progress) =>
        set(progress >= 1 ? { progress: 1, status: "analysing" } : { progress }),
      );
      set(loaded(report));
    } catch (error) {
      set({ status: "error", error: toAppError(error) });
    }
  },
  analyseSample: async () => {
    set({ status: "analysing", progress: 1, upload: null, error: null });
    try {
      set(loaded(await postWithProgress("/api/sample?lang=" + get().lang, undefined)));
    } catch (error) {
      set({ status: "error", error: toAppError(error) });
    }
  },
  expire: () => set({ status: "error", report: null, bench: null, view: "report", explore: null, error: { code: "expired" } }),
  setView: (view) => set({ view }),
  openExplorer: (explore) => {
    set({ view: "explorer", explore });
    window.scrollTo({ top: 0 });
  },
  setExportOpen: (exportOpen) => set({ exportOpen }),
  reset: () => set({ status: "idle", report: null, bench: null, error: null, progress: 0, view: "report", explore: null }),
}));

export const useT = () => dictionaries[useStore((s) => s.lang)];
