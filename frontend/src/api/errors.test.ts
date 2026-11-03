import { AxiosError } from "axios";
import { describe, expect, it } from "vitest";
import { describeError, formatWait } from "./errors";

function httpError(status: number, data: unknown, headers: Record<string, string> = {}) {
  const response = { status, data, headers, statusText: "", config: {} } as never;
  return new AxiosError("x", String(status), undefined, null, response);
}

describe("formatWait", () => {
  it("rounds up to whole minutes", () => {
    expect(formatWait(61)).toBe("2 minutes");
    expect(formatWait(600)).toBe("10 minutes");
  });
  it("handles very short and very long waits", () => {
    expect(formatWait(20)).toBe("about a minute");
    expect(formatWait(7200)).toBe("about 2 hours");
  });
});

describe("describeError", () => {
  it("shows the reason for a rejected target", () => {
    expect(describeError(httpError(422, { detail: "Target host is not on the allowlist" }))).toBe(
      "Target host is not on the allowlist",
    );
  });
  it("falls back to a form message for validation arrays", () => {
    expect(describeError(httpError(422, { detail: [{ msg: "bad" }] }))).toMatch(/check the form/i);
  });
  it("adds a retry time to 429 messages", () => {
    const msg = describeError(httpError(429, { detail: "Daily request budget used." }, { "retry-after": "1800" }));
    expect(msg).toBe("Daily request budget used. Try again in 30 minutes.");
  });
  it("still reads well without Retry-After", () => {
    expect(describeError(httpError(429, { detail: "Too many runs." }))).toBe("Too many runs.");
  });
  it("hides server internals on 500", () => {
    expect(describeError(httpError(500, { detail: "Traceback ..." }))).not.toMatch(/Traceback/);
  });
});
