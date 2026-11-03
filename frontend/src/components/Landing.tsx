import { useState } from "react";
import { GITHUB_URL, REQUEST_ACCESS_HREF } from "../config";

interface LandingProps {
  // Why the visitor is here (expired session, bad link, ...). Null on first visit.
  notice: string | null;
  // Resolves to an error message, or null when login worked.
  onLogin: (code: string) => Promise<string | null>;
}

const MONO = "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace";

const linkStyle: React.CSSProperties = { color: "#a78bfa", textDecoration: "underline" };

export default function Landing({ notice, onLogin }: LandingProps) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (code.trim() === "" || busy) return;
    setBusy(true);
    setError(null);
    const failure = await onLogin(code.trim());
    // Success unmounts this component; only reset state when it stays on screen.
    if (failure !== null) {
      setError(failure);
      setBusy(false);
    }
  }

  const message = error ?? notice;

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0f", color: "#ccd6f6" }}>
      <main
        className="qs-main"
        style={{ maxWidth: 760, margin: "0 auto", display: "flex", flexDirection: "column", gap: 28 }}
      >
        <header>
          <p style={{ margin: 0, fontFamily: MONO, fontWeight: 700, fontSize: 18, color: "#e6f1ff" }}>
            QueryScope
          </p>
          <h1 style={{ margin: "14px 0 10px", fontSize: 28, lineHeight: 1.25, color: "#e6f1ff" }}>
            Load-test an API, then ask what changed in plain English
          </h1>
          <p style={{ margin: 0, fontSize: 15, lineHeight: 1.65 }}>
            QueryScope runs benchmarks against REST endpoints, stores every request latency in
            PostgreSQL, and flags regressions against a baseline run. A retrieval pipeline over
            Azure AI Search lets you ask questions like "which run got slower and why?". This
            hosted demo is invite-only and limited to a small set of safe targets.
          </p>
        </header>

        {/* Replace with a screenshot or GIF of the dashboard. */}
        <div
          role="img"
          aria-label="Screenshot of the QueryScope dashboard (coming soon)"
          style={{
            border: "1px dashed #2e3150",
            borderRadius: 12,
            minHeight: 180,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#8892b0",
            fontSize: 13,
            background: "#0f0f1a",
            textAlign: "center",
            padding: 16,
          }}
        >
          Screenshot or GIF placeholder
        </div>

        <section
          aria-labelledby="enter-code"
          style={{ background: "#0f0f1a", border: "1px solid #1a1a2e", borderRadius: 12, padding: "20px 18px" }}
        >
          <h2 id="enter-code" style={{ margin: "0 0 12px", fontSize: 16, color: "#e6f1ff" }}>
            Enter your access code
          </h2>

          {message && (
            <div
              role="alert"
              style={{
                marginBottom: 12,
                padding: "9px 14px",
                background: "rgba(239,68,68,0.08)",
                border: "1px solid rgba(239,68,68,0.25)",
                borderRadius: 8,
                color: "#fca5a5",
                fontSize: 14,
              }}
            >
              {message}
            </div>
          )}

          <form onSubmit={(e) => void submit(e)} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <label htmlFor="access-code" style={{ fontSize: 13, color: "#8892b0" }}>
              Access code
            </label>
            <input
              id="access-code"
              type="password"
              name="access-code"
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              style={{
                padding: "9px 12px",
                background: "#13131f",
                border: "1px solid #2e3150",
                borderRadius: 8,
                color: "#e6f1ff",
                fontFamily: MONO,
                fontSize: 14,
              }}
            />
            <button
              type="submit"
              disabled={busy || code.trim() === ""}
              style={{
                padding: "10px 20px",
                background: busy || code.trim() === "" ? "#13131f" : "#7c3aed",
                border: "1px solid #7c3aed",
                borderRadius: 8,
                color: "#fff",
                fontWeight: 600,
                fontSize: 14,
                cursor: busy ? "wait" : "pointer",
              }}
            >
              {busy ? "Checking…" : "Enter"}
            </button>
          </form>
        </section>

        <p style={{ margin: 0, fontSize: 14, lineHeight: 1.7 }}>
          No code yet?{" "}
          <a href={REQUEST_ACCESS_HREF} style={linkStyle}>
            Request access by email
          </a>
          . The source is on{" "}
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" style={linkStyle}>
            GitHub
          </a>
          .
        </p>
      </main>
    </div>
  );
}
