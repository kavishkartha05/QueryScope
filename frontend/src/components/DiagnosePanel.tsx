import { useState } from "react";
import client from "../api/client";
import type { DiagnoseResponse } from "../types/run";

const EXAMPLE_QUESTIONS = [
  "Why did p99 spike?",
  "Compare my last two runs",
  "Which endpoint is slowest?",
  "Are there signs of degradation?",
];

// ── Typing indicator ────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5, padding: "6px 0" }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "#7c3aed",
            display: "inline-block",
            animation: `qs-bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
          }}
        />
      ))}
    </div>
  );
}

// ── Panel ───────────────────────────────────────────────────────────────────

export default function DiagnosePanel() {
  const [question, setQuestion] = useState("");
  const [diagnosis, setDiagnosis] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focused, setFocused] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setDiagnosis(null);
    setError(null);

    try {
      const res = await client.post<DiagnoseResponse>("/benchmark/diagnose", { question });
      setDiagnosis(res.data.diagnosis);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h2
        style={{
          margin: "0 0 20px",
          fontSize: 13,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          color: "#8892b0",
        }}
      >
        AI Diagnosis
      </h2>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="Ask about latency patterns, error rates, or degradation…"
          rows={3}
          required
          style={{
            width: "100%",
            padding: "10px 12px",
            background: "#13131f",
            border: `1px solid ${focused ? "#7c3aed" : "#1a1a2e"}`,
            boxShadow: focused ? "0 0 0 3px rgba(124,58,237,0.18)" : "none",
            borderRadius: 8,
            color: "#e6f1ff",
            fontSize: 13,
            fontFamily:
              "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
            resize: "vertical",
            outline: "none",
            transition: "border-color 0.2s, box-shadow 0.2s",
            lineHeight: 1.6,
            boxSizing: "border-box",
          }}
        />

        {/* Example chips */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {EXAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => setQuestion(q)}
              style={{
                padding: "3px 11px",
                background: "#13131f",
                border: "1px solid #1a1a2e",
                borderRadius: 20,
                color: "#8892b0",
                fontSize: 11,
                cursor: "pointer",
                fontFamily:
                  "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                transition: "border-color 0.15s, color 0.15s",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "#7c3aed";
                (e.currentTarget as HTMLButtonElement).style.color = "#ccd6f6";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "#1a1a2e";
                (e.currentTarget as HTMLButtonElement).style.color = "#8892b0";
              }}
            >
              {q}
            </button>
          ))}
        </div>

        <button
          type="submit"
          disabled={loading || question.trim() === ""}
          style={{
            alignSelf: "flex-start",
            padding: "9px 22px",
            background:
              loading || question.trim() === "" ? "#13131f" : "#7c3aed",
            border: "1px solid",
            borderColor:
              loading || question.trim() === "" ? "#1a1a2e" : "#7c3aed",
            borderRadius: 8,
            color:
              loading || question.trim() === "" ? "#8892b0" : "#fff",
            fontSize: 13,
            fontWeight: 600,
            cursor: loading || question.trim() === "" ? "not-allowed" : "pointer",
            display: "flex",
            alignItems: "center",
            gap: 8,
            transition: "background 0.2s",
            letterSpacing: "0.04em",
          }}
        >
          {loading ? (
            <>
              <span
                style={{
                  width: 12,
                  height: 12,
                  border: "2px solid #8892b0",
                  borderTopColor: "transparent",
                  borderRadius: "50%",
                  animation: "qs-spin 0.7s linear infinite",
                  display: "inline-block",
                  flexShrink: 0,
                }}
              />
              Diagnosing…
            </>
          ) : (
            "Diagnose"
          )}
        </button>
      </form>

      {loading && (
        <div style={{ marginTop: 16 }}>
          <TypingIndicator />
        </div>
      )}

      {error && (
        <div
          style={{
            marginTop: 16,
            padding: "10px 14px",
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.2)",
            borderRadius: 8,
            color: "#ef4444",
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      {diagnosis && (
        <div
          style={{
            marginTop: 16,
            padding: "16px 20px",
            background: "#13131f",
            border: "1px solid #1a1a2e",
            borderLeft: "3px solid #7c3aed",
            borderRadius: 8,
            fontSize: 13,
            lineHeight: 1.75,
            color: "#ccd6f6",
            whiteSpace: "pre-wrap",
          }}
        >
          {diagnosis}
        </div>
      )}
    </div>
  );
}
