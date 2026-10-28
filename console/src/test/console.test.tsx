import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnswerText, EvidenceCard, ToolTrace } from "../features/ask/Answer";
import { priceColour, Strip, summarise } from "../features/ask/PriceStrip";
import { segments, valueAt } from "../features/ask/segments";
import { EvalsPage } from "../features/evals/EvalsPage";
import type { Answer, Interval, NumberCheck } from "../shared/api/client";
import { ErrorState } from "../shared/ui/states";

const n = (text: string, start: number, grounded = true, path = "average"): NumberCheck => ({
  text,
  value: Number.parseFloat(text),
  unit: "EUR/MWh",
  start,
  end: start + text.length,
  grounded,
  evidence: grounded ? "e1" : null,
  source: grounded ? "call_1" : null,
  path: grounded ? path : null,
  reason: "",
});

const answer: Answer = {
  question: "q",
  answer: "Averaged 83.03 EUR/MWh; next month 95.40 EUR/MWh.",
  skill: null,
  redacted: false,
  corrections: 0,
  model_calls: 2,
  ms: 10,
  numbers: [n("95.40 EUR/MWh", 35, false), n("83.03 EUR/MWh", 9)],
  tool_calls: [{ name: "price_stats", input: { zone: "DE-LU" }, ok: true, call_id: "call_1", denied_by: [], error: null, result: { average: 83.03 } }],
};

function wrap(ui: ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>;
}

afterEach(() => vi.restoreAllMocks());

describe("segments", () => {
  it("splits text and numbers in order, whatever order the checks come in", () => {
    const s = segments(answer.answer, answer.numbers);
    expect(s.map((x) => x.kind)).toEqual(["text", "number", "text", "number", "text"]);
    expect(s.map((x) => x.text).join("")).toBe(answer.answer);
  });
  it("skips a number that redaction removed", () => {
    const s = segments("Averaged 83.03 EUR/MWh.", answer.numbers);
    expect(s.filter((x) => x.kind === "number")).toHaveLength(1);
  });
  it("reads JSON paths", () => {
    expect(valueAt({ a: { b: [1, { c: 7 }] } }, "a.b[1].c")).toBe(7);
  });
});

describe("answer", () => {
  it("marks traced and untraced numbers and selects them", async () => {
    const onSelect = vi.fn();
    render(<AnswerText answer={answer} selected={null} onSelect={onSelect} />);
    const bad = screen.getByRole("button", { name: /95.40 EUR\/MWh: not traced/ });
    expect(bad.className).toContain("num-untraced");
    await userEvent.click(screen.getByRole("button", { name: /83.03 EUR\/MWh: from call_1/ }));
    expect(onSelect).toHaveBeenCalledWith(0);
  });
  it("shows the tool and field behind a number", () => {
    render(<EvidenceCard check={answer.numbers[1]!} calls={answer.tool_calls} />);
    expect(screen.getByText("price_stats")).toBeTruthy();
    expect(screen.getByText("83.03")).toBeTruthy();
  });
  it("shows policy refusals in the trace", () => {
    render(<ToolTrace skill={null} calls={[{ name: "hedge_report", input: { books: ["trading-de"] }, ok: false, call_id: "c", denied_by: ["own-desk-books"], error: "not permitted", result: null }]} />);
    expect(screen.getByText("own-desk-books")).toBeTruthy();
  });
});

describe("price strip", () => {
  const day: Interval[] = Array.from({ length: 96 }, (_, i) => ({ at: `2026-08-12 ${String(Math.floor(i / 4)).padStart(2, "0")}:${String((i % 4) * 15).padStart(2, "0")}`, da: i === 52 ? -7 : i === 77 ? 115 : 60, solar_mw: 0, wind_mw: 0 }));
  it("summarises the day", () => {
    expect(summarise(day)).toMatchObject({ lo: { da: -7 }, hi: { da: 115 }, negativeHours: 0.25 });
  });
  it("colours negative prices differently", () => {
    expect(priceColour(-1)).toBe("var(--price-negative)");
    expect(priceColour(200)).toBe("var(--price-scarce)");
  });
  it("is keyboard explorable", async () => {
    render(<Strip intervals={day} />);
    const svg = screen.getByRole("img");
    svg.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(document.querySelector(".strip-readout")?.textContent).toContain("60.00 EUR/MWh");
    expect(svg.querySelectorAll("rect")).toHaveLength(96);
  });
});

describe("states", () => {
  it("evals page: loading then empty held-out", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ heldout: {} }), { status: 200 }));
    render(wrap(<EvalsPage />));
    expect(screen.getByRole("status")).toBeTruthy();
    expect(await screen.findByText("No first run recorded")).toBeTruthy();
    expect(screen.getByText("No reports yet")).toBeTruthy();
  });
  it("evals page: error with retry", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "boom" }), { status: 500 }));
    render(wrap(<EvalsPage />));
    expect(await screen.findByRole("alert")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(f).toHaveBeenCalledTimes(2);
  });
  it("explains an expired sign-in", () => {
    render(<ErrorState what="x" error={Object.assign(new (class extends Error {})(), {})} />);
    expect(screen.getByRole("alert").textContent).toContain("did not answer");
  });
});
