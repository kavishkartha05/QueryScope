// Keep a typed number inside [min, max]; blanks and junk fall back to min.
export function clampInt(raw: string | number, min: number, max: number): number {
  const n = typeof raw === "number" ? raw : parseInt(raw, 10);
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, Math.trunc(n)));
}
