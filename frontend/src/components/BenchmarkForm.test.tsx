import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import BenchmarkForm from "./BenchmarkForm";
import { CONFIG, installFakeApi } from "../test/fakeApi";

describe("BenchmarkForm", () => {
  it("offers the allowed targets and states the limits", () => {
    render(<BenchmarkForm config={CONFIG} onRunCreated={() => {}} />);
    expect(screen.getByRole("option", { name: "httpbin.org" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "QueryScope demo target" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /custom url/i })).toBeNull();
    expect(screen.getByLabelText(/requests \(max 500\)/i)).toHaveAttribute("max", "500");
    expect(screen.getByLabelText(/concurrency \(max 20\)/i)).toHaveAttribute("max", "20");
    expect(screen.getByLabelText(/timeout s \(max 10\)/i)).toHaveAttribute("max", "10");
  });

  it("clamps typed values to the caps", async () => {
    render(<BenchmarkForm config={CONFIG} onRunCreated={() => {}} />);
    const reqs = screen.getByLabelText(/requests \(max 500\)/i);
    await userEvent.clear(reqs);
    await userEvent.type(reqs, "9999");
    expect(reqs).toHaveValue(500);
  });

  it("allows a custom URL only when the server says so", () => {
    render(<BenchmarkForm config={{ ...CONFIG, allow_custom_target: true }} onRunCreated={() => {}} />);
    expect(screen.getByRole("option", { name: /custom url/i })).toBeInTheDocument();
  });

  it("sends the chosen target and caps-bound values", async () => {
    const seen = installFakeApi(() => ({ status: 202, data: { run_id: "12345678-aaaa" } }));
    render(<BenchmarkForm config={CONFIG} onRunCreated={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText(/^target/i), "https://demo.example.com/work");
    await userEvent.click(screen.getByRole("button", { name: /run benchmark/i }));
    const body = JSON.parse(String(seen[0].data));
    expect(body.target_url).toBe("https://demo.example.com/work");
    expect(body.timeout_s).toBeLessThanOrEqual(10);
    expect(await screen.findByRole("status")).toHaveTextContent(/12345678/);
  });

  it("shows a friendly retry message on 429", async () => {
    installFakeApi(() => ({
      status: 429,
      data: { detail: "Daily request budget used." },
      headers: { "retry-after": "1800" },
    }));
    render(<BenchmarkForm config={CONFIG} onRunCreated={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /run benchmark/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 30 minutes.");
  });

  it("shows the server's reason on 422", async () => {
    installFakeApi(() => ({ status: 422, data: { detail: "That target is not allowed." } }));
    render(<BenchmarkForm config={CONFIG} onRunCreated={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /run benchmark/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That target is not allowed.");
  });
});
