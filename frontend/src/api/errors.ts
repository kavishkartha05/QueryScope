import axios from "axios";

export function formatWait(seconds: number): string {
  if (seconds <= 60) return "about a minute";
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `${minutes} minutes`;
  const hours = Math.ceil(minutes / 60);
  return hours === 1 ? "about an hour" : `about ${hours} hours`;
}

function readRetryAfter(headers: unknown): number | null {
  if (!headers || typeof headers !== "object") return null;
  const raw = (headers as Record<string, unknown>)["retry-after"];
  if (raw === undefined || raw === null) return null;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * Turn any request error into text a person can act on.
 *   401 -> handled by the interceptor, but give a fallback message
 *   422 -> the server's reason (target rejected) or a generic form message
 *   429 -> the server's reason plus "try again in N minutes" from Retry-After
 * Never includes request bodies, codes or tokens.
 */
export function describeError(err: unknown): string {
  if (!axios.isAxiosError(err)) {
    return "Something went wrong. Please try again.";
  }
  if (!err.response) {
    return "Cannot reach the QueryScope API. Check your connection and try again.";
  }
  const status = err.response.status;
  const data = err.response.data as { detail?: unknown } | undefined;
  const detail = typeof data?.detail === "string" ? data.detail : null;

  if (status === 401) {
    return "Your session has expired. Enter your access code to continue.";
  }
  if (status === 422) {
    return detail ?? "Those values were not accepted. Check the form and try again.";
  }
  if (status === 429) {
    const wait = readRetryAfter(err.response.headers);
    const base = detail ?? "You have reached a usage limit.";
    return wait === null ? base : `${base} Try again in ${formatWait(wait)}.`;
  }
  if (status === 404) {
    return detail ?? "That item was not found.";
  }
  if (status === 403) {
    return detail ?? "That action is not allowed.";
  }
  if (status >= 500) {
    return "The server had a problem. Please try again in a moment.";
  }
  return detail ?? "Request failed. Please try again.";
}
