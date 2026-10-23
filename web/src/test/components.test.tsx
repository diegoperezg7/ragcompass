import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Explorer } from "../components/Explorer";
import { Home } from "../components/Home";
import { Recommendations } from "../components/Recommendations";
import { TooltipProvider } from "../components/ui";
import { useStore } from "../store";
import type { Report } from "../types";
import chunks from "./chunks-handbook.json";
import sample from "./sample-report.json";

const report = sample as unknown as Report;

beforeEach(() => {
  useStore.setState({ lang: "en", status: "idle", report: null, error: null, explore: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Recommendations", () => {
  it("shows each setting with its basis and expands the reason on demand", () => {
    render(<Recommendations report={report} />);
    const card = screen.getByText("Chunking: documents").closest("article")!;
    expect(within(card).getByText(/rule-based|measured/)).toBeTruthy();
    const toggle = within(card).getByRole("button", { name: /Why/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const reason = report.recommendations.find((r) => r.key === "chunking.documents")!.reason_i18n.en;
    expect(within(card).getByText(reason)).toBeTruthy();
  });

  it("follows the language switch", () => {
    render(<Recommendations report={report} />);
    act(() => useStore.setState({ lang: "es" }));
    expect(screen.getByText("Recomendaciones")).toBeTruthy();
  });
});

describe("Home", () => {
  it("refuses too many files before uploading anything", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<Home />);
    const files = Array.from({ length: 501 }, (_, i) => new File(["x"], `f${i}.md`));
    await act(() => useStore.getState().analyseFiles(files));
    expect(screen.getByRole("alert").textContent).toMatch(/Too many files/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("Explorer", () => {
  it("marks chunk boundaries and damaged chunks, and moves with the keyboard", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(chunks), { status: 200 })));
    useStore.setState({ report, status: "done", explore: { file: "onboarding-handbook.md", strategy: "fixed", size: 128, overlap: 0 } });
    render(
      <TooltipProvider>
        <Explorer report={report} />
      </TooltipProvider>,
    );
    await act(() => vi.advanceTimersByTimeAsync(300));
    await waitFor(() => expect(document.querySelectorAll(".chunk")).toHaveLength(chunks.chunks.length));
    vi.useRealTimers();

    const url = String((fetch as unknown as { mock: { calls: string[][] } }).mock.calls[0][0]);
    expect(url).toContain(`/api/report/${report.id}/chunks?file=onboarding-handbook.md&strategy=fixed&size=128&overlap=0`);
    const damaged = chunks.chunks.filter((c) => c.issues.some((i) => i.kind !== "tiny")).length;
    expect(document.querySelectorAll(".mm-seg.bad")).toHaveLength(damaged);
    expect(screen.getAllByText("sentence cut").length).toBeGreaterThan(0);

    const list = screen.getByLabelText("Chunks of the selected file");
    expect(screen.getByText(`Chunk 1 / ${chunks.chunks.length}`)).toBeTruthy();
    fireEvent.keyDown(list, { key: "j" });
    expect(screen.getByText(`Chunk 2 / ${chunks.chunks.length}`)).toBeTruthy();
    expect(document.querySelector(".chunk.selected")?.getAttribute("data-index")).toBe("1");
  });
});
