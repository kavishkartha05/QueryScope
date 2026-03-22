import type { Run, RunStatus } from "../types/run";

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

interface RunsTableProps {
  runs: Run[];
  total: number;
  error: string | null;
}

export default function RunsTable({ runs, total, error }: RunsTableProps) {
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
