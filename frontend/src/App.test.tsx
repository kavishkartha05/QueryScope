import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { resetBootForTests } from "./api/auth";
import { getToken } from "./api/session";
import { CONFIG, installFakeApi } from "./test/fakeApi";

// Recharts needs layout APIs jsdom lacks; the chart is not under test here.
vi.mock("./components/LatencyChart", () => ({ default: () => <div>chart</div> }));
vi.mock("./components/DiagnosePanel", () => ({ default: () => <div>diagnose</div> }));

const RUNS = { total: 0, offset: 0, limit: 20, items: [] };

beforeEach(() => {
  resetBootForTests();
  window.history.replaceState(null, "", "/");
});

describe("App", () => {
  it("shows the landing page with no token", async () => {
    installFakeApi(() => ({ status: 401 }));
    render(<App />);
    expect(await screen.findByRole("heading", { name: /enter your access code/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /request access/i }).getAttribute("href")).toMatch(/^mailto:/);
    expect(screen.getByRole("link", { name: /github/i }).getAttribute("href")).toBe(
      "https://github.com/kavishkartha05/QueryScope",
    );
  });

  it("logs in with a code and reaches the dashboard", async () => {
    let authed = false;
    installFakeApi((c) => {
      if (c.url === "/auth/login") {
        authed = true;
        return { status: 200, data: { token: "tok", label: "demo" } };
      }
      if (!authed) return { status: 401 };
      return c.url === "/config" ? { status: 200, data: CONFIG } : { status: 200, data: RUNS };
    });
    render(<App />);
    await userEvent.type(await screen.findByLabelText(/^access code$/i), "demo.abc1234567");
    await userEvent.click(screen.getByRole("button", { name: /enter/i }));
    expect(await screen.findByRole("button", { name: /run benchmark/i })).toBeInTheDocument();
    expect(getToken()).toBe("tok");
  });

  it("shows a generic error for a bad code and stays on the landing page", async () => {
    installFakeApi((c) => (c.url === "/auth/login" ? { status: 401, data: { detail: "Invalid access code" } } : { status: 401 }));
    render(<App />);
    await userEvent.type(await screen.findByLabelText(/^access code$/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /enter/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not recognized/i);
  });

  it("returns to the landing page with a message when a request gets a 401", async () => {
    window.sessionStorage.setItem("qs_token", "stale");
    let calls = 0;
    installFakeApi((c) => {
      if (c.url === "/config") return { status: 200, data: CONFIG };
      calls += 1;
      return { status: 401 };
    });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/expired or was revoked/i);
    expect(getToken()).toBeNull();
    expect(calls).toBeGreaterThan(0);
  });

  it("exchanges a magic link on load and removes the fragment", async () => {
    window.history.replaceState(null, "", "/#code=lbl.abcdefghij");
    installFakeApi((c) => {
      if (c.url === "/auth/login") return { status: 200, data: { token: "tok", label: "lbl" } };
      return c.url === "/config" ? { status: 200, data: CONFIG } : { status: 200, data: RUNS };
    });
    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: /run benchmark/i })).toBeInTheDocument());
    expect(window.location.hash).toBe("");
  });
});
