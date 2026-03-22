import { useState } from "react";
import client from "../api/client";
import type { DiagnoseResponse } from "../types/run";

export default function DiagnosePanel() {
  const [question, setQuestion] = useState("");
  const [diagnosis, setDiagnosis] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setDiagnosis(null);
    setError(null);

    try {
      const res = await client.post<DiagnoseResponse>("/benchmark/diagnose", {
        question,
      });
      setDiagnosis(res.data.diagnosis);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h2>Diagnose</h2>
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8 }}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Why did p99 spike in the last run?"
          required
          style={{ flex: 1, padding: "6px 10px", fontSize: 14 }}
        />
        <button type="submit" disabled={loading || question.trim() === ""}>
          {loading ? "Diagnosing…" : "Diagnose"}
        </button>
      </form>

      {error && (
        <p style={{ color: "#c62828", margin: 0, fontSize: 13 }}>{error}</p>
      )}

      {diagnosis && (
        <div
          style={{
            background: "#f5f5f5",
            border: "1px solid #ddd",
            borderRadius: 4,
            padding: "12px 16px",
            fontSize: 14,
            lineHeight: 1.6,
            whiteSpace: "pre-wrap", // preserve line breaks in the diagnosis
          }}
        >
          {diagnosis}
        </div>
      )}
    </div>
  );
}
