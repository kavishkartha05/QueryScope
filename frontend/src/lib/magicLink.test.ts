import { describe, expect, it } from "vitest";
import { codeFromHash, stripFragment } from "./magicLink";

describe("codeFromHash", () => {
  it("reads the code", () => {
    expect(codeFromHash("#code=stripe-rebecca.aB3dE5gH7k")).toBe("stripe-rebecca.aB3dE5gH7k");
  });
  it("returns null when absent or empty", () => {
    expect(codeFromHash("")).toBeNull();
    expect(codeFromHash("#other=1")).toBeNull();
    expect(codeFromHash("#code=")).toBeNull();
  });
});

describe("stripFragment", () => {
  it("removes the fragment and keeps the path", () => {
    window.history.replaceState(null, "", "/app?x=1#code=abc");
    stripFragment();
    expect(window.location.hash).toBe("");
    expect(window.location.pathname + window.location.search).toBe("/app?x=1");
  });
});
