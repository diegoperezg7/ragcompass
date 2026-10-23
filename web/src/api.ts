import type { Bench, ChunkView, ExportTarget, Projection, Report } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }

  /** The server forgot the report (restart or TTL): the client has to analyse again. */
  get expired() {
    return this.status === 404 && this.message !== "Not Found";
  }
}

function detailOf(status: number, statusText: string, body: string): string {
  try {
    const detail = JSON.parse(body).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return status ? `${status} ${statusText}` : "network error";
}

/** POST with upload progress, which fetch cannot report. */
export function postWithProgress(url: string, body: FormData | undefined, onProgress?: (fraction: number) => void) {
  return new Promise<Report>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.upload.onload = () => onProgress?.(1);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new ApiError("invalid response from the server", xhr.status));
        }
      } else reject(new ApiError(detailOf(xhr.status, xhr.statusText, xhr.responseText), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("network error", 0));
    xhr.send(body);
  });
}

async function call(url: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError("network error", 0);
  }
  if (!response.ok) throw new ApiError(detailOf(response.status, response.statusText, await response.text()), response.status);
  return response;
}

const reportUrl = (report: Report, path = "") => `/api/report/${encodeURIComponent(report.id ?? "")}${path}`;

export async function renderReport(report: Report, format: "md" | "yaml", lang: string): Promise<string> {
  const init = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(report) };
  return (await call(`/api/render?format=${format}&lang=${lang}`, init)).text();
}

export interface ChunkQuery {
  file: string;
  strategy?: string;
  size?: number;
  overlap?: number;
  /** Chunk to select when the explorer opens; not sent to the server. */
  focus?: number;
}

export async function fetchChunks(report: Report, query: ChunkQuery, signal?: AbortSignal): Promise<ChunkView> {
  const params = new URLSearchParams({ file: query.file });
  if (query.strategy) params.set("strategy", query.strategy);
  if (query.size) params.set("size", String(query.size));
  if (query.overlap !== undefined) params.set("overlap", String(query.overlap));
  return (await call(`${reportUrl(report, "/chunks")}?${params}`, { signal })).json();
}

/** Stored report, refreshed after a benchmark so recommendations carry their measured basis. */
export async function fetchReport(report: Report, lang: string): Promise<Report> {
  return (await call(`${reportUrl(report)}?lang=${lang}`)).json();
}

export async function runBench(report: Report, lang: string, dense = import.meta.env.VITE_BENCH_DENSE !== "false"): Promise<Bench> {
  return (await call(`${reportUrl(report, "/bench")}?lang=${lang}&dense=${dense}`, { method: "POST" })).json();
}

export async function fetchProjection(report: Report): Promise<Projection> {
  return (await call(reportUrl(report, "/projection"))).json();
}

export async function fetchExport(report: Report, target: ExportTarget): Promise<string> {
  return (await call(`${reportUrl(report, "/export")}?target=${target}`)).text();
}
