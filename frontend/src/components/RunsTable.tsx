import { useEffect, useState } from "react";
import client from "../api/client";
import type { PaginatedRuns, Run, RunStatus } from "../types/run";

const STATUS_COLOR: Record<RunStatus, string> = {
  pending: "#888",
  running: "#d4a017",
  done: "#2e7d32",
  failed: "#c62828",
};

function fmt(n: number | undefined): string {
  return n !== undefined ? n.toFixed(1) + " ms" : "—";
}

function truncateId(id: string): string {
  // Show first 8 chars — enough to identify a run visually.
  return id.slice(0, 8) + "…";
}

export default function RunsTable() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function fetchRuns() {
    try {
      const res = await client.get<PaginatedRuns>("/benchmark/runs");
      setRuns(res.data.items);
      setTotal(res.data.total);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to fetch runs");
    }
  }

  useEffect(() => {
    void fetchRuns();

    // Poll every 3 s so in-progress runs update without a manual refresh.
    // Interval is cleared on unmount to avoid state updates on dead components.
    const id = setInterval(() => void fetchRuns(), 3000);
    return () => clearInterval(id);
  }, []);

  return (
    <div>
      <h2>Runs ({total})</h2>
      {error && <p style={{ color: "red" }}>{error}</p>}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            {["ID", "URL", "Method", "Status", "p50", "p95", "p99", "Created"].map(
              (col) => (
                <th
                  key={col}
                  style={{ textAlign: "left", padding: "6px 8px", borderBottom: "1px solid #ccc" }}
                >
                  {col}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>
                {truncateId(run.id)}
              </td>
              <td style={{ padding: "6px 8px", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {run.target_url}
              </td>
              <td style={{ padding: "6px 8px" }}>{run.method}</td>
              <td style={{ padding: "6px 8px", color: STATUS_COLOR[run.status], fontWeight: 600 }}>
                {run.status}
              </td>
              <td style={{ padding: "6px 8px" }}>{fmt(run.metrics?.p50)}</td>
              <td style={{ padding: "6px 8px" }}>{fmt(run.metrics?.p95)}</td>
              <td style={{ padding: "6px 8px" }}>{fmt(run.metrics?.p99)}</td>
              <td style={{ padding: "6px 8px" }}>
                {new Date(run.created_at).toLocaleString()}
              </td>
            </tr>
          ))}
          {runs.length === 0 && (
            <tr>
              <td colSpan={8} style={{ padding: "12px 8px", color: "#888" }}>
                No runs yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
