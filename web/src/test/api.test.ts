import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchExport, runBench } from "../api";
import type { Report } from "../types";
import sample from "./sample-report.json";

const report = sample as unknown as Report;

function respond(status: number, body: unknown) {
  return vi.fn(async () => new Response(typeof body === "string" ? body : JSON.stringify(body), { status, statusText: "x" }));
}

afterEach(() => vi.unstubAllGlobals());

describe("endpoints that may not exist yet", () => {
  it("falls back to preview data when the route is missing", async () => {
    vi.stubGlobal("fetch", respond(404, { detail: "Not Found" }));
    const { data, preview } = await runBench(report, "en");
    expect(preview).toBe(true);
    expect(data.configs.length).toBeGreaterThan(0);
    expect(data.configs.filter((c) => c.recommended)).toHaveLength(1);
  });

  it("treats an unknown report as expired instead of faking data", async () => {
    vi.stubGlobal("fetch", respond(404, { detail: "unknown or expired report_id" }));
    const error = await runBench(report, "en").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.expired).toBe(true);
  });

  it("uses the server answer when there is one", async () => {
    vi.stubGlobal("fetch", respond(200, "splitter = 1\n"));
    expect(await fetchExport(report, "langchain", "en")).toEqual({ data: "splitter = 1\n", preview: false });
  });

  it("passes other errors through", async () => {
    vi.stubGlobal("fetch", respond(422, { detail: [{ msg: "bad size" }] }));
    await expect(fetchExport(report, "haystack", "en")).rejects.toMatchObject({ status: 422, message: "bad size" });
  });
});
