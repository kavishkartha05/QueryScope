import { useState } from "react";
import client from "../api/client";
import type { BenchmarkRequest, RunCreatedResponse } from "../types/run";

interface BenchmarkFormProps {
  onRunCreated: (runId: string) => void;
}

const HTTP_METHODS = ["GET", "POST", "PUT", "DELETE"] as const;
type HttpMethod = (typeof HTTP_METHODS)[number];

export default function BenchmarkForm({ onRunCreated }: BenchmarkFormProps) {
  const [targetUrl, setTargetUrl] = useState("");
  const [method, setMethod] = useState<HttpMethod>("GET");
  const [numRequests, setNumRequests] = useState(50);
  const [concurrency, setConcurrency] = useState(5);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    const payload: BenchmarkRequest = {
      target_url: targetUrl,
      method,
      num_requests: numRequests,
      concurrency,
    };

    try {
      const res = await client.post<RunCreatedResponse>("/benchmark", payload);
      onRunCreated(res.data.run_id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h2>New Benchmark</h2>

      <label>
        Target URL
        <input
          type="url"
          value={targetUrl}
          onChange={(e) => setTargetUrl(e.target.value)}
          placeholder="https://example.com/api"
          required
          style={{ display: "block", width: "100%", marginTop: 4 }}
        />
      </label>

      <label>
        Method
        <select
          value={method}
          onChange={(e) => setMethod(e.target.value as HttpMethod)}
          style={{ display: "block", marginTop: 4 }}
        >
          {HTTP_METHODS.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </label>

      <label>
        Number of Requests: {numRequests}
        <input
          type="number"
          min={1}
          max={10000}
          value={numRequests}
          onChange={(e) => setNumRequests(Number(e.target.value))}
          style={{ display: "block", marginTop: 4 }}
        />
      </label>

      <label>
        Concurrency: {concurrency}
        {/* Slider capped at 20 — matches the "week-1 keep it simple" ethos;
            high concurrency from the browser is rarely meaningful anyway. */}
        <input
          type="range"
          min={1}
          max={20}
          value={concurrency}
          onChange={(e) => setConcurrency(Number(e.target.value))}
          style={{ display: "block", width: "100%", marginTop: 4 }}
        />
      </label>

      {error && <p style={{ color: "red" }}>{error}</p>}

      <button type="submit" disabled={submitting}>
        {submitting ? "Running…" : "Run Benchmark"}
      </button>
    </form>
  );
}
