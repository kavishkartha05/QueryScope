import { describe, expect, it } from "vitest";
import { clampInt } from "./numbers";

describe("clampInt", () => {
  it("keeps values inside the range", () => {
    expect(clampInt("9999", 1, 500)).toBe(500);
    expect(clampInt("0", 1, 500)).toBe(1);
    expect(clampInt("42", 1, 500)).toBe(42);
  });
  it("falls back to the minimum for junk", () => {
    expect(clampInt("", 1, 500)).toBe(1);
    expect(clampInt("abc", 1, 20)).toBe(1);
  });
});
