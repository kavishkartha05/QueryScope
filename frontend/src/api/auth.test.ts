import { beforeEach, describe, expect, it } from "vitest";
import { bootstrap, loginWithCode } from "./auth";
import { getToken } from "./session";
import { CONFIG, installFakeApi } from "../test/fakeApi";

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("loginWithCode", () => {
  it("stores the token in sessionStorage only", async () => {
    installFakeApi(() => ({ status: 200, data: { token: "tok-1", label: "demo" } }));
    expect(await loginWithCode("some-code")).toBeNull();
    expect(getToken()).toBe("tok-1");
    expect(window.localStorage.length).toBe(0);
  });

  it("gives one generic message for a bad code", async () => {
    installFakeApi(() => ({ status: 401, data: { detail: "Invalid access code" } }));
    const msg = await loginWithCode("nope");
    expect(msg).toMatch(/not recognized/i);
    expect(getToken()).toBeNull();
  });

  it("explains throttling with a wait time", async () => {
    installFakeApi(() => ({ status: 429, data: {}, headers: { "retry-after": "600" } }));
    expect(await loginWithCode("x")).toBe("Too many attempts. Try again in 10 minutes.");
  });
});

describe("bootstrap", () => {
  it("exchanges a #code= link, strips the fragment, then loads config", async () => {
    window.history.replaceState(null, "", "/#code=lbl.abcDEF1234");
    const seen = installFakeApi((c) =>
      c.url === "/auth/login"
        ? { status: 200, data: { token: "tok-2", label: "lbl" } }
        : { status: 200, data: CONFIG },
    );
    const result = await bootstrap();
    expect(result.kind).toBe("authed");
    expect(window.location.hash).toBe("");
    const cfgReq = seen[seen.length - 1];
    expect(cfgReq.headers.Authorization).toBe("Bearer tok-2");
  });

  it("shows the landing page with a message when the link fails", async () => {
    window.history.replaceState(null, "", "/#code=revoked.zzzzzzzzzz");
    installFakeApi((c) => (c.url === "/auth/login" ? { status: 401 } : { status: 401 }));
    const result = await bootstrap();
    expect(result.kind).toBe("anon");
    if (result.kind === "anon") expect(result.message).toMatch(/link is not valid/i);
    expect(window.location.hash).toBe("");
    expect(getToken()).toBeNull();
  });

  it("goes straight to the app when the server has auth disabled", async () => {
    installFakeApi(() => ({ status: 200, data: { ...CONFIG, auth_enabled: false } }));
    expect((await bootstrap()).kind).toBe("authed");
  });

  it("returns to landing without a message on a first visit", async () => {
    installFakeApi(() => ({ status: 401 }));
    expect(await bootstrap()).toEqual({ kind: "anon", message: null });
  });
});
