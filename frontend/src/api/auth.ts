import axios from "axios";
import client from "./client";
import { codeFromHash, stripFragment } from "../lib/magicLink";
import { clearSession, getToken, saveSession } from "./session";
import { formatWait } from "./errors";
import type { AppConfig } from "../types/config";

interface LoginResponse {
  token: string;
  label: string;
}

export const BAD_CODE_MESSAGE =
  "That access code was not recognized. Check it and try again, or request access below.";

/** Exchange a code for a token and store it. Returns null on success, else a message. */
export async function loginWithCode(code: string): Promise<string | null> {
  try {
    const res = await client.post<LoginResponse>("/auth/login", { code });
    saveSession(res.data.token, res.data.label ?? null);
    return null;
  } catch (err: unknown) {
    if (axios.isAxiosError(err) && err.response) {
      const status = err.response.status;
      if (status === 429) {
        const raw = Number(err.response.headers["retry-after"]);
        const wait = Number.isFinite(raw) && raw > 0 ? ` Try again in ${formatWait(raw)}.` : "";
        return "Too many attempts." + wait;
      }
      if (status === 401) return BAD_CODE_MESSAGE;
      if (status === 404) return null; // Auth disabled on the server: nothing to log into.
    }
    return "Could not reach the QueryScope API. Please try again.";
  }
}

export type BootResult =
  | { kind: "authed"; config: AppConfig }
  | { kind: "anon"; message: string | null };

/**
 * Decide what to show on load:
 *   1. a #code= link is exchanged (and the fragment removed first)
 *   2. otherwise GET /config tells us whether the token (or an open server) works
 */
export async function bootstrap(): Promise<BootResult> {
  const linkCode = codeFromHash(window.location.hash);
  if (linkCode !== null) {
    // Strip before the network call so the code never lingers in the URL.
    stripFragment();
    clearSession();
    const failure = await loginWithCode(linkCode);
    if (failure !== null) {
      return { kind: "anon", message: failure === BAD_CODE_MESSAGE ? "This access link is not valid or has been revoked. Enter your code below or request access." : failure };
    }
  }
  return fetchConfig();
}

export async function fetchConfig(): Promise<BootResult> {
  try {
    const res = await client.get<AppConfig>("/config");
    return { kind: "authed", config: res.data };
  } catch (err: unknown) {
    if (axios.isAxiosError(err) && err.response?.status === 401) {
      const hadToken = getToken() !== null;
      clearSession();
      return {
        kind: "anon",
        message: hadToken ? "Your session has expired. Enter your access code to continue." : null,
      };
    }
    return { kind: "anon", message: "Could not reach the QueryScope API. Please try again shortly." };
  }
}

// Memoised so React StrictMode's double effect run does not exchange a magic
// link twice (the second pass would find the fragment already stripped).
let bootPromise: Promise<BootResult> | null = null;
export function getBoot(): Promise<BootResult> {
  if (bootPromise === null) bootPromise = bootstrap();
  return bootPromise;
}
export function resetBootForTests(): void {
  bootPromise = null;
}
