import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchChunks, fetchExport, runBench } from "../api";
import type { Report } from "../types";
import sample from "./sample-report.json";

const report = sample as unknown as Report;

function respond(status: number, body: unknown) {
  return vi.fn(async () => new Response(typeof body === "string" ? body : JSON.stringify(body), { status, statusText: "x" }));
}

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("builds the explorer query from the report id", async () => {
    const fetchSpy = respond(200, { chunks: [] });
    vi.stubGlobal("fetch", fetchSpy);
    await fetchChunks(report, { file: "kb/a b.md", strategy: "fixed", size: 128, overlap: 0 });
    expect(String((fetchSpy.mock.calls[0] as unknown[])[0])).toBe(`/api/report/${report.id}/chunks?file=kb%2Fa+b.md&strategy=fixed&size=128&overlap=0`);
  });

  it("flags an unknown report as expired so the client can analyse again", async () => {
    vi.stubGlobal("fetch", respond(404, { detail: "unknown or expired report_id" }));
    const error = await runBench(report, "en").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.expired).toBe(true);
  });

  it("does not mistake a missing route for an expired report", async () => {
    vi.stubGlobal("fetch", respond(404, { detail: "Not Found" }));
    const error = await fetchExport(report, "haystack").catch((e) => e);
    expect(error.expired).toBe(false);
  });

  it("returns export snippets as text", async () => {
    vi.stubGlobal("fetch", respond(200, "splitter = 1\n"));
    expect(await fetchExport(report, "langchain")).toBe("splitter = 1\n");
  });

  it("joins validation errors into one message", async () => {
    vi.stubGlobal("fetch", respond(422, { detail: [{ msg: "bad size" }, { msg: "bad overlap" }] }));
    await expect(fetchChunks(report, { file: "a.md", size: 1 })).rejects.toMatchObject({ status: 422, message: "bad size; bad overlap" });
  });

  it("reports network failures with status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    await expect(fetchExport(report, "yaml")).rejects.toMatchObject({ status: 0 });
  });
});
