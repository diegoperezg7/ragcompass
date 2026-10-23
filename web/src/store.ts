import { create } from "zustand";
import { dictionaries, type Lang } from "./i18n";
import type { Report } from "./types";

type Theme = "light" | "dark";
type Status = "idle" | "loading" | "done" | "error";

interface State {
  lang: Lang;
  theme: Theme;
  status: Status;
  report: Report | null;
  error: string | null;
  setLang: (lang: Lang) => void;
  toggleTheme: () => void;
  analyseFiles: (files: File[]) => Promise<void>;
  analyseSample: () => Promise<void>;
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

const initialTheme: Theme =
  stored("ragcompass.theme", ["light", "dark"] as const) ??
  (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
const initialLang: Lang =
  stored("ragcompass.lang", ["en", "es"] as const) ?? (navigator.language.startsWith("es") ? "es" : "en");

document.documentElement.dataset.theme = initialTheme;
document.documentElement.lang = initialLang;

async function request(url: string, body?: FormData): Promise<Report> {
  const response = await fetch(url, { method: "POST", body });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(String(detail));
  }
  return response.json();
}

export const useStore = create<State>((set, get) => ({
  lang: initialLang,
  theme: initialTheme,
  status: "idle",
  report: null,
  error: null,
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
    const form = new FormData();
    for (const file of files) {
      const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
      form.append("files", file, relative);
    }
    set({ status: "loading", error: null });
    try {
      set({ report: await request("/api/analyze", form), status: "done" });
    } catch (error) {
      set({ status: "error", error: (error as Error).message });
    }
  },
  analyseSample: async () => {
    set({ status: "loading", error: null });
    try {
      set({ report: await request("/api/sample"), status: "done" });
    } catch (error) {
      set({ status: "error", error: (error as Error).message });
    }
  },
  reset: () => set({ status: "idle", report: null, error: null }),
}));

export const useT = () => dictionaries[useStore((s) => s.lang)];
