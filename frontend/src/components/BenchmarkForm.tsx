import { useState } from "react";
import client from "../api/client";
import type { BenchmarkRequest, RunCreatedResponse } from "../types/run";

interface BenchmarkFormProps {
  onRunCreated: (runId: string) => void;
}

const HTTP_METHODS = ["GET", "POST", "PUT", "DELETE"] as const;
type HttpMethod = (typeof HTTP_METHODS)[number];

const baseInput: React.CSSProperties = {
  width: "100%",
  padding: "9px 12px",
  background: "#13131f",
  border: "1px solid #1a1a2e",
  borderRadius: 8,
  color: "#e6f1ff",
  fontSize: 13,
  fontFamily: "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
  outline: "none",
  transition: "border-color 0.2s, box-shadow 0.2s",
  boxSizing: "border-box",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  color: "#8892b0",
  marginBottom: 6,
};

export default function BenchmarkForm({ onRunCreated }: BenchmarkFormProps) {
  const [targetUrl, setTargetUrl] = useState("");
  const [method, setMethod] = useState<HttpMethod>("GET");
  const [numRequests, setNumRequests] = useState(50);
  const [concurrency, setConcurrency] = useState(5);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successId, setSuccessId] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);

  function inputStyle(name: string): React.CSSProperties {
    return {
      ...baseInput,
      borderColor: focused === name ? "#7c3aed" : "#1a1a2e",
      boxShadow: focused === name ? "0 0 0 3px rgba(124,58,237,0.18)" : "none",
    };
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccessId(null);
    setSubmitting(true);

    const payload: BenchmarkRequest = {
      target_url: targetUrl,
      method,
      num_requests: numRequests,
      concurrency,
    };

    try {
      const res = await client.post<RunCreatedResponse>("/benchmark", payload);
      setSuccessId(res.data.run_id);
      onRunCreated(res.data.run_id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <h2
        style={{
          margin: "0 0 24px",
          fontSize: 13,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          color: "#8892b0",
        }}
      >
        New Benchmark
      </h2>

      {/* Row 1: URL + Method */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 130px",
          gap: 12,
          marginBottom: 12,
        }}
      >
        <div>
          <label style={labelStyle}>Target URL</label>
          <input
            type="text"
            value={targetUrl}
            onChange={(e) => setTargetUrl(e.target.value)}
            onFocus={() => setFocused("url")}
            onBlur={() => setFocused(null)}
            placeholder="https://api.example.com/endpoint"
            required
            style={inputStyle("url")}
          />
        </div>
        <div>
          <label style={labelStyle}>Method</label>
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as HttpMethod)}
            onFocus={() => setFocused("method")}
            onBlur={() => setFocused(null)}
            style={{
              ...inputStyle("method"),
              cursor: "pointer",
              appearance: "none",
            }}
          >
            {HTTP_METHODS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Row 2: Requests + Concurrency */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
          marginBottom: 20,
        }}
      >
        <div>
          <label style={labelStyle}>Requests</label>
          <input
            type="number"
            min={1}
            max={10000}
            value={numRequests}
            onChange={(e) => setNumRequests(Number(e.target.value))}
            onFocus={() => setFocused("reqs")}
            onBlur={() => setFocused(null)}
            style={inputStyle("reqs")}
          />
        </div>
        <div>
          <label style={labelStyle}>
            Concurrency
            <span
              style={{
                marginLeft: 8,
                color: "#7c3aed",
                fontSize: 12,
                fontFamily:
                  "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                textTransform: "none",
                letterSpacing: 0,
              }}
            >
              {concurrency}
            </span>
          </label>
          <input
            type="range"
            min={1}
            max={20}
            value={concurrency}
            onChange={(e) => setConcurrency(Number(e.target.value))}
            style={{ width: "100%", accentColor: "#7c3aed", cursor: "pointer" }}
          />
        </div>
      </div>

      {error && (
        <div
          style={{
            marginBottom: 14,
            padding: "9px 14px",
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.25)",
            borderRadius: 8,
            color: "#ef4444",
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      {successId && (
        <div
          style={{
            marginBottom: 14,
            padding: "9px 14px",
            background: "rgba(16,185,129,0.08)",
            border: "1px solid rgba(16,185,129,0.25)",
            borderRadius: 8,
            color: "#10b981",
            fontSize: 12,
            fontFamily:
              "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
          }}
        >
          Started — run_id: {successId}
        </div>
      )}

      <button
        type="submit"
        disabled={submitting}
        style={{
          width: "100%",
          padding: "10px 20px",
          background: submitting ? "#13131f" : "#7c3aed",
          border: "1px solid",
          borderColor: submitting ? "#1a1a2e" : "#7c3aed",
          borderRadius: 8,
          color: submitting ? "#8892b0" : "#fff",
          fontSize: 13,
          fontWeight: 600,
          cursor: submitting ? "not-allowed" : "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          transition: "background 0.2s",
          letterSpacing: "0.04em",
        }}
      >
        {submitting ? (
          <>
            <span
              style={{
                width: 13,
                height: 13,
                border: "2px solid #8892b0",
                borderTopColor: "transparent",
                borderRadius: "50%",
                animation: "qs-spin 0.7s linear infinite",
                display: "inline-block",
                flexShrink: 0,
              }}
            />
            Running…
          </>
        ) : (
          "Run Benchmark"
        )}
      </button>
    </form>
  );
}
