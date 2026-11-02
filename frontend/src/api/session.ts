// Token storage. sessionStorage, never localStorage: the token disappears when
// the tab closes and is not shared across tabs. Nothing here logs its values.

const TOKEN_KEY = "qs_token";
const LABEL_KEY = "qs_label";

export function getToken(): string | null {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getLabel(): string | null {
  try {
    return window.sessionStorage.getItem(LABEL_KEY);
  } catch {
    return null;
  }
}

export function saveSession(token: string, label: string | null): void {
  try {
    window.sessionStorage.setItem(TOKEN_KEY, token);
    if (label) window.sessionStorage.setItem(LABEL_KEY, label);
  } catch {
    // Storage blocked: the session lasts until reload, which is acceptable.
  }
}

export function clearSession(): void {
  try {
    window.sessionStorage.removeItem(TOKEN_KEY);
    window.sessionStorage.removeItem(LABEL_KEY);
  } catch {
    // Nothing to clear.
  }
}

// ── Unauthorized notification ──────────────────────────────────────────────
// The axios interceptor cannot touch React state, so it calls a listener that
// the App registers.

type Listener = () => void;
let unauthorizedListener: Listener | null = null;

export function setUnauthorizedListener(fn: Listener | null): void {
  unauthorizedListener = fn;
}

export function notifyUnauthorized(): void {
  if (unauthorizedListener) unauthorizedListener();
}
