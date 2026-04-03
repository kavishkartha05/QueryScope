import { useEffect, useState } from "react";
import client from "../api/client";
import type { BenchmarkRequest, RunCreatedResponse } from "../types/run";

interface BenchmarkFormProps {
  onRunCreated: (runId: string) => void;
  // Incrementing this value triggers a reset of the SLA fields so they don't
  // carry over into the next benchmark after a session reset.
  resetKey?: number;
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

export default function BenchmarkForm({ onRunCreated, resetKey }: BenchmarkFormProps) {
  const [targetUrl, setTargetUrl] = useState("");
  const [method, setMethod] = useState<HttpMethod>("GET");
  const [numRequests, setNumRequests] = useState(50);
  const [concurrency, setConcurrency] = useState(5);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successId, setSuccessId] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);

  // SLA section
  const [slaOpen, setSlaOpen] = useState(false);
  const [slaP50, setSlaP50] = useState("");
  const [slaP95, setSlaP95] = useState("");
  const [slaP99, setSlaP99] = useState("");
  const [slaAvg, setSlaAvg] = useState("");
  const [slaErr, setSlaErr] = useState("");

  // Clear SLA fields and collapse the section whenever the parent resets the
  // session. resetKey starts at 0, so the effect is skipped on first render.
  useEffect(() => {
    if (!resetKey) return;
    setSlaP50("");
    setSlaP95("");
    setSlaP99("");
    setSlaAvg("");
    setSlaErr("");
    setSlaOpen(false);
  }, [resetKey]);

  function inputStyle(name: string): React.CSSProperties {
    return {
      ...baseInput,
      borderColor: focused === name ? "#7c3aed" : "#1a1a2e",
      boxShadow: focused === name ? "0 0 0 3px rgba(124,58,237,0.18)" : "none",
    };
  }

  function parseSla(raw: string): number | undefined {
    const n = parseFloat(raw);
    return raw.trim() !== "" && !isNaN(n) ? n : undefined;
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

    // Only include SLA fields that the user actually filled in.
    const p50 = parseSla(slaP50);
    const p95 = parseSla(slaP95);
    const p99 = parseSla(slaP99);
    const avg = parseSla(slaAvg);
    const err = parseSla(slaErr);
    if (p50 !== undefined) payload.sla_p50_ms = p50;
    if (p95 !== undefined) payload.sla_p95_ms = p95;
    if (p99 !== undefined) payload.sla_p99_ms = p99;
    if (avg !== undefined) payload.sla_avg_latency_ms = avg;
    if (err !== undefined) payload.sla_error_rate_pct = err;

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

      {/* SLA Thresholds — collapsible */}
      <div style={{ marginBottom: 20 }}>
        <button
          type="button"
          onClick={() => setSlaOpen((o) => !o)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            background: "none",
            border: "none",
            padding: 0,
            cursor: "pointer",
            color: slaOpen ? "#a78bfa" : "#8892b0",
            fontSize: 11,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            transition: "color 0.15s",
          }}
        >
          {/* Chevron rotates when open */}
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{
              transform: slaOpen ? "rotate(90deg)" : "rotate(0deg)",
              transition: "transform 0.2s",
              flexShrink: 0,
            }}
          >
            <polyline points="9 18 15 12 9 6" />
          </svg>
          SLA Thresholds
          {(slaP50 || slaP95 || slaP99 || slaAvg || slaErr) && (
            <span
              style={{
                padding: "1px 7px",
                borderRadius: 10,
                background: "rgba(167,139,250,0.12)",
                border: "1px solid rgba(167,139,250,0.28)",
                color: "#a78bfa",
                fontSize: 10,
                letterSpacing: "0.04em",
              }}
            >
              configured
            </span>
          )}
        </button>

        {slaOpen && (
          <div
            style={{
              marginTop: 14,
              padding: "16px 18px",
              background: "rgba(167,139,250,0.04)",
              border: "1px solid rgba(167,139,250,0.14)",
              borderRadius: 10,
            }}
          >
            <p
              style={{
                margin: "0 0 14px",
                fontSize: 12,
                color: "#8892b0",
                lineHeight: 1.5,
              }}
            >
              Leave any field blank to skip that threshold. A run is marked{" "}
              <span style={{ color: "#ef4444", fontWeight: 600 }}>SLA Fail</span>{" "}
              if any configured threshold is exceeded.
            </p>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 1fr",
                gap: 12,
                marginBottom: 12,
              }}
            >
              <div>
                <label style={labelStyle}>P50 (ms)</label>
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={slaP50}
                  onChange={(e) => setSlaP50(e.target.value)}
                  onFocus={() => setFocused("slaP50")}
                  onBlur={() => setFocused(null)}
                  placeholder="e.g. 200"
                  style={inputStyle("slaP50")}
                />
              </div>
              <div>
                <label style={labelStyle}>P95 (ms)</label>
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={slaP95}
                  onChange={(e) => setSlaP95(e.target.value)}
                  onFocus={() => setFocused("slaP95")}
                  onBlur={() => setFocused(null)}
                  placeholder="e.g. 500"
                  style={inputStyle("slaP95")}
                />
              </div>
              <div>
                <label style={labelStyle}>P99 (ms)</label>
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={slaP99}
                  onChange={(e) => setSlaP99(e.target.value)}
                  onFocus={() => setFocused("slaP99")}
                  onBlur={() => setFocused(null)}
                  placeholder="e.g. 1000"
                  style={inputStyle("slaP99")}
                />
              </div>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 12,
              }}
            >
              <div>
                <label style={labelStyle}>Avg Latency (ms)</label>
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={slaAvg}
                  onChange={(e) => setSlaAvg(e.target.value)}
                  onFocus={() => setFocused("slaAvg")}
                  onBlur={() => setFocused(null)}
                  placeholder="e.g. 250"
                  style={inputStyle("slaAvg")}
                />
              </div>
              <div>
                <label style={labelStyle}>Error Rate (%)</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  step="any"
                  value={slaErr}
                  onChange={(e) => setSlaErr(e.target.value)}
                  onFocus={() => setFocused("slaErr")}
                  onBlur={() => setFocused(null)}
                  placeholder="e.g. 1"
                  style={inputStyle("slaErr")}
                />
              </div>
            </div>
          </div>
        )}
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
