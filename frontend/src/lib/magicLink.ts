/** Read `code` from a URL fragment like "#code=abc.def". Null if absent. */
export function codeFromHash(hash: string): string | null {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  if (raw === "") return null;
  const code = new URLSearchParams(raw).get("code");
  return code && code.trim() !== "" ? code.trim() : null;
}

/**
 * Remove the fragment (and only the fragment) so the code is not left in the
 * address bar, history entry or a later copy-paste of the URL.
 */
export function stripFragment(): void {
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}
