import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RunsTable from "./RunsTable";
import type { Run } from "../types/run";

function run(over: Partial<Run>): Run {
  return {
    id: "aaaaaaaa-0000-0000-0000-000000000000",
    target_url: "https://httpbin.org/get",
    method: "GET",
    num_requests: 10,
    concurrency: 2,
    status: "done",
    is_baseline: false,
    is_demo: false,
    created_at: new Date().toISOString(),
    metrics: { p50: 10, p95: 20, p99: 30, throughput: 5, error_rate: 0 },
    ...over,
  };
}

const noop = async () => {};

describe("RunsTable", () => {
  it("labels demo runs as examples and disables pinning them", () => {
    render(<RunsTable runs={[run({ is_demo: true })]} total={1} error={null} onSetBaseline={noop} onClearBaseline={noop} />);
    expect(screen.getByText("Example")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /read-only/i })).toBeDisabled();
  });

  it("lets the caller pin their own run", async () => {
    const pin = vi.fn(noop);
    render(<RunsTable runs={[run({})]} total={1} error={null} onSetBaseline={pin} onClearBaseline={noop} />);
    await userEvent.click(screen.getByRole("button", { name: /pin as baseline/i }));
    expect(pin).toHaveBeenCalledWith("aaaaaaaa-0000-0000-0000-000000000000");
  });

  it("offers Clear only when the baseline is the caller's own", () => {
    const own = run({ is_baseline: true });
    const { rerender } = render(<RunsTable runs={[own]} total={1} error={null} onSetBaseline={noop} onClearBaseline={noop} />);
    expect(screen.getByRole("button", { name: /clear my baseline/i })).toBeInTheDocument();
    rerender(<RunsTable runs={[run({ is_baseline: true, is_demo: true })]} total={1} error={null} onSetBaseline={noop} onClearBaseline={noop} />);
    expect(screen.queryByRole("button", { name: /clear my baseline/i })).toBeNull();
    expect(screen.getByText(/example baseline/i)).toBeInTheDocument();
  });

  it("shows regression deltas against the baseline", () => {
    render(<RunsTable runs={[run({ delta_p50_pct: 25 })]} total={1} error={null} onSetBaseline={noop} onClearBaseline={noop} />);
    expect(screen.getByText("+25%")).toBeInTheDocument();
  });

  it("reads failed runs as timed out, not as a raw error", () => {
    render(<RunsTable runs={[run({ status: "failed", metrics: null })]} total={1} error={null} onSetBaseline={noop} onClearBaseline={noop} />);
    expect(screen.getByText(/timed out or failed/i)).toBeInTheDocument();
  });

  it("has no reset-session control", () => {
    render(<RunsTable runs={[]} total={0} error={null} onSetBaseline={noop} onClearBaseline={noop} />);
    expect(screen.queryByText(/reset session/i)).toBeNull();
  });
});
