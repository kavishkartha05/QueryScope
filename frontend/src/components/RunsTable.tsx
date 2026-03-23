import { useState } from "react";
import type { Run, RunStatus } from "../types/run";

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt(n: number | undefined): string {
  return n !== undefined ? n.toFixed(1) : "—";
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Status badge ───────────────────────────────────────────────────────────

const STATUS_CFG: Record<
  RunStatus,
  { color: string; bg: string; border: string; label: string; dotAnim: string }
> = {
  pending: {
    color: "#fbbf24",
    bg: "rgba(251,191,36,0.10)",
    border: "rgba(251,191,36,0.28)",
    label: "pending",
    dotAnim: "qs-pulse 1.4s ease-in-out infinite",
  },
  running: {
    color: "#60a5fa",
    bg: "rgba(96,165,250,0.10)",
    border: "rgba(96,165,250,0.28)",
    label: "running",
    dotAnim: "qs-spin 1s linear infinite",
  },
  done: {
    color: "#10b981",
    bg: "rgba(16,185,129,0.10)",
    border: "rgba(16,185,129,0.28)",
    label: "done",
    dotAnim: "none",
  },
  failed: {
    color: "#ef4444",
    bg: "rgba(239,68,68,0.10)",
    border: "rgba(239,68,68,0.28)",
    label: "failed",
    dotAnim: "none",
  },
};

function StatusBadge({ status }: { status: RunStatus }) {
  const cfg = STATUS_CFG[status];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "2px 9px",
        borderRadius: 20,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        color: cfg.color,
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
      }}
    >
      <span
        style={{
          width: 5,
          height: 5,
          borderRadius: "50%",
          background: cfg.color,
          display: "inline-block",
          flexShrink: 0,
          animation: cfg.dotAnim,
          border:
            status === "running" ? `1.5px solid ${cfg.color}` : "none",
          borderTopColor:
            status === "running" ? "transparent" : undefined,
        }}
      />
      {cfg.label}
    </span>
  );
}

// ── Tooltip ────────────────────────────────────────────────────────────────

function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  const [show, setShow] = useState(false);
  return (
    <span
      style={{ position: "relative", cursor: "default" }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <span
          style={{
            position: "absolute",
            bottom: "calc(100% + 6px)",
            left: 0,
            background: "#13131f",
            border: "1px solid #2a2a40",
            borderRadius: 6,
            padding: "4px 9px",
            fontSize: 11,
            fontFamily:
              "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
            color: "#ccd6f6",
            whiteSpace: "nowrap",
            boxShadow: "0 4px 20px rgba(0,0,0,0.5)",
            zIndex: 50,
            pointerEvents: "none",
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}

// ── Table ──────────────────────────────────────────────────────────────────

interface RunsTableProps {
  runs: Run[];
  total: number;
  error: string | null;
}

const TH: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 14px",
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  color: "#8892b0",
  borderBottom: "1px solid #1a1a2e",
  whiteSpace: "nowrap",
};

const TD: React.CSSProperties = {
  padding: "11px 14px",
  fontSize: 13,
  borderBottom: "1px solid #1a1a2e",
  color: "#ccd6f6",
};

export default function RunsTable({ runs, total, error }: RunsTableProps) {
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          marginBottom: 18,
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: 13,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            color: "#8892b0",
          }}
        >
          Benchmark Runs
        </h2>
        <span
          style={{
            fontSize: 11,
            fontFamily:
              "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
            color: "#7c3aed",
            background: "rgba(124,58,237,0.12)",
            padding: "1px 8px",
            borderRadius: 10,
            border: "1px solid rgba(124,58,237,0.28)",
          }}
        >
          {total}
        </span>
      </div>

      {error && (
        <div
          style={{
            marginBottom: 14,
            padding: "8px 14px",
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.2)",
            borderRadius: 8,
            color: "#ef4444",
            fontSize: 12,
          }}
        >
          {error}
        </div>
      )}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {["ID", "URL", "Method", "Status", "p50 ms", "p95 ms", "p99 ms", "When"].map(
                (col) => (
                  <th key={col} style={TH}>
                    {col}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr
                key={run.id}
                onMouseEnter={() => setHoveredRow(run.id)}
                onMouseLeave={() => setHoveredRow(null)}
                style={{
                  background:
                    hoveredRow === run.id
                      ? "rgba(124,58,237,0.04)"
                      : "transparent",
                  transition: "background 0.15s",
                }}
              >
                <td
                  style={{
                    ...TD,
                    fontFamily:
                      "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                    fontSize: 11,
                  }}
                >
                  <Tip text={run.id}>{run.id.slice(0, 8)}…</Tip>
                </td>
                <td style={{ ...TD, maxWidth: 220 }}>
                  <Tip text={run.target_url}>
                    <span
                      style={{
                        display: "block",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        maxWidth: 220,
                        fontFamily:
                          "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                        fontSize: 11,
                        color: "#8892b0",
                      }}
                    >
                      {run.target_url}
                    </span>
                  </Tip>
                </td>
                <td
                  style={{
                    ...TD,
                    fontFamily:
                      "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                    fontSize: 11,
                  }}
                >
                  {run.method}
                </td>
                <td style={TD}>
                  <StatusBadge status={run.status} />
                </td>
                <td
                  style={{
                    ...TD,
                    fontFamily:
                      "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                    color: "#10b981",
                  }}
                >
                  {fmt(run.metrics?.p50)}
                </td>
                <td
                  style={{
                    ...TD,
                    fontFamily:
                      "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                    color: "#f59e0b",
                  }}
                >
                  {fmt(run.metrics?.p95)}
                </td>
                <td
                  style={{
                    ...TD,
                    fontFamily:
                      "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                    color: "#ef4444",
                  }}
                >
                  {fmt(run.metrics?.p99)}
                </td>
                <td style={{ ...TD, color: "#8892b0", fontSize: 12 }}>
                  {relativeTime(run.created_at)}
                </td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr>
                <td
                  colSpan={8}
                  style={{
                    ...TD,
                    textAlign: "center",
                    padding: "36px 14px",
                    color: "#8892b0",
                    fontSize: 13,
                  }}
                >
                  No runs yet. Submit a benchmark above.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
