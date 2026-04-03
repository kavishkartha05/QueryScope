import { Fragment, useState } from "react";
import type { Run, RunStatus, SlaThresholdResult } from "../types/run";

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

// Human-readable labels and units for each SLA metric key.
const METRIC_META: Record<string, { label: string; unit: string }> = {
  p50_ms: { label: "P50", unit: "ms" },
  p95_ms: { label: "P95", unit: "ms" },
  p99_ms: { label: "P99", unit: "ms" },
  avg_latency_ms: { label: "Avg Latency", unit: "ms" },
  error_rate_pct: { label: "Error Rate", unit: "%" },
};

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
          border: status === "running" ? `1.5px solid ${cfg.color}` : "none",
          borderTopColor: status === "running" ? "transparent" : undefined,
        }}
      />
      {cfg.label}
    </span>
  );
}

// ── Baseline badge ─────────────────────────────────────────────────────────

function BaselineBadge() {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 20,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.07em",
        textTransform: "uppercase",
        color: "#a78bfa",
        background: "rgba(167,139,250,0.12)",
        border: "1px solid rgba(167,139,250,0.30)",
        marginLeft: 6,
        verticalAlign: "middle",
      }}
    >
      Baseline
    </span>
  );
}

// ── Delta chip ─────────────────────────────────────────────────────────────

function DeltaChip({ value }: { value: number }) {
  const negligible = Math.abs(value) <= 2;
  const regression = value > 2;

  const color = negligible ? "#6b7280" : regression ? "#ef4444" : "#10b981";
  const bg = negligible
    ? "rgba(107,114,128,0.10)"
    : regression
    ? "rgba(239,68,68,0.12)"
    : "rgba(16,185,129,0.12)";
  const border = negligible
    ? "rgba(107,114,128,0.25)"
    : regression
    ? "rgba(239,68,68,0.30)"
    : "rgba(16,185,129,0.30)";

  const sign = value > 0 ? "+" : "";
  const label = `${sign}${Math.round(value)}%`;

  return (
    <span
      style={{
        display: "inline-block",
        marginLeft: 5,
        padding: "1px 6px",
        borderRadius: 10,
        fontSize: 10,
        fontWeight: 700,
        fontFamily:
          "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
        color,
        background: bg,
        border: `1px solid ${border}`,
        verticalAlign: "middle",
        letterSpacing: "0.02em",
      }}
    >
      {label}
    </span>
  );
}

// ── SLA badge ──────────────────────────────────────────────────────────────

function SlaBadge({
  status,
  onClick,
}: {
  status: "pass" | "fail";
  onClick: () => void;
}) {
  const pass = status === "pass";
  return (
    <button
      type="button"
      onClick={onClick}
      title="Click to view threshold breakdown"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "2px 9px",
        borderRadius: 20,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        cursor: "pointer",
        color: pass ? "#10b981" : "#ef4444",
        background: pass ? "rgba(16,185,129,0.10)" : "rgba(239,68,68,0.10)",
        border: `1px solid ${pass ? "rgba(16,185,129,0.28)" : "rgba(239,68,68,0.28)"}`,
        transition: "filter 0.15s",
      }}
      onMouseEnter={(e) =>
        ((e.currentTarget as HTMLButtonElement).style.filter = "brightness(1.2)")
      }
      onMouseLeave={(e) =>
        ((e.currentTarget as HTMLButtonElement).style.filter = "none")
      }
    >
      {pass ? "✓" : "✕"} SLA {pass ? "Pass" : "Fail"}
    </button>
  );
}

// ── SLA breakdown row ──────────────────────────────────────────────────────

function SlaBreakdownRow({
  thresholds,
  colSpan,
}: {
  thresholds: SlaThresholdResult[];
  colSpan: number;
}) {
  return (
    <tr>
      <td
        colSpan={colSpan}
        style={{
          padding: "0 14px 14px 46px",
          borderBottom: "1px solid #1a1a2e",
        }}
      >
        <table
          style={{
            width: "100%",
            maxWidth: 560,
            borderCollapse: "collapse",
            fontSize: 12,
            fontFamily:
              "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
          }}
        >
          <thead>
            <tr>
              {["Metric", "Target", "Actual", "Delta", ""].map((h) => (
                <th
                  key={h}
                  style={{
                    textAlign: "left",
                    padding: "5px 10px",
                    fontSize: 10,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                    color: "#8892b0",
                    borderBottom: "1px solid #1a1a2e",
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {thresholds.map((t) => {
              const meta = METRIC_META[t.metric] ?? { label: t.metric, unit: "" };
              const overBudget = t.delta > 0;
              const deltaSign = t.delta > 0 ? "+" : "";
              const deltaStr = `${deltaSign}${t.delta.toFixed(1)}${meta.unit}`;

              return (
                <tr key={t.metric}>
                  <td style={{ padding: "5px 10px", color: "#ccd6f6" }}>
                    {meta.label}
                  </td>
                  <td style={{ padding: "5px 10px", color: "#8892b0" }}>
                    {t.target.toFixed(1)}
                    {meta.unit}
                  </td>
                  <td style={{ padding: "5px 10px", color: "#ccd6f6" }}>
                    {t.actual.toFixed(1)}
                    {meta.unit}
                  </td>
                  <td
                    style={{
                      padding: "5px 10px",
                      color: overBudget ? "#ef4444" : "#10b981",
                      fontWeight: 600,
                    }}
                  >
                    {deltaStr}
                  </td>
                  <td style={{ padding: "5px 10px" }}>
                    <span
                      style={{
                        display: "inline-block",
                        padding: "1px 8px",
                        borderRadius: 10,
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: "0.06em",
                        textTransform: "uppercase",
                        color: t.status === "pass" ? "#10b981" : "#ef4444",
                        background:
                          t.status === "pass"
                            ? "rgba(16,185,129,0.10)"
                            : "rgba(239,68,68,0.10)",
                        border: `1px solid ${
                          t.status === "pass"
                            ? "rgba(16,185,129,0.28)"
                            : "rgba(239,68,68,0.28)"
                        }`,
                      }}
                    >
                      {t.status}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </td>
    </tr>
  );
}

// ── Pin button ─────────────────────────────────────────────────────────────

function PinButton({ active, onClick }: { active: boolean; onClick: () => void }) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      title={active ? "Current baseline" : "Pin as baseline"}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: "none",
        border: "none",
        cursor: active ? "default" : "pointer",
        padding: "2px 4px",
        borderRadius: 4,
        color: active ? "#a78bfa" : hovered ? "#ccd6f6" : "#3d3d5c",
        transition: "color 0.15s",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <svg
        width="13"
        height="13"
        viewBox="0 0 24 24"
        fill={active ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <line x1="12" y1="17" x2="12" y2="22" />
        <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z" />
      </svg>
    </button>
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
  onReset: () => Promise<void>;
  onSetBaseline: (runId: string) => Promise<void>;
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

const COL_COUNT = 10; // pin + ID + URL + Method + Status + SLA + p50 + p95 + p99 + When

export default function RunsTable({ runs, total, error, onReset, onSetBaseline }: RunsTableProps) {
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);
  // ID of the run whose SLA breakdown is currently expanded.
  const [expandedSla, setExpandedSla] = useState<string | null>(null);

  const hasBaseline = runs.some((r) => r.is_baseline);

  function toggleSla(runId: string) {
    setExpandedSla((prev) => (prev === runId ? null : runId));
  }

  async function handleReset() {
    if (!window.confirm("Reset session? This will delete all benchmark runs and clear the diagnosis history.")) {
      return;
    }
    await onReset();
  }

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 18,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
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

        <button
          onClick={() => void handleReset()}
          style={{
            padding: "4px 12px",
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.25)",
            borderRadius: 6,
            color: "#ef4444",
            fontSize: 11,
            fontWeight: 600,
            cursor: "pointer",
            letterSpacing: "0.04em",
            transition: "background 0.15s, border-color 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "rgba(239,68,68,0.15)";
            (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(239,68,68,0.45)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "rgba(239,68,68,0.08)";
            (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(239,68,68,0.25)";
          }}
        >
          Reset Session
        </button>
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

      {runs.length > 0 && !hasBaseline && (
        <div
          style={{
            marginBottom: 14,
            padding: "8px 14px",
            background: "rgba(167,139,250,0.06)",
            border: "1px solid rgba(167,139,250,0.18)",
            borderRadius: 8,
            color: "#8892b0",
            fontSize: 12,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="17" x2="12" y2="22" />
            <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z" />
          </svg>
          Pin a completed run as baseline to track regressions across future runs
        </div>
      )}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {["", "ID", "URL", "Method", "Status", "SLA", "p50 ms", "p95 ms", "p99 ms", "When"].map(
                (col) => (
                  <th
                    key={col}
                    style={col === "" ? { ...TH, width: 32, padding: "10px 6px" } : TH}
                  >
                    {col}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const slaStatus = run.sla_result?.status;
              const slaExpanded = expandedSla === run.id;

              return (
                <Fragment key={run.id}>
                  <tr
                    onMouseEnter={() => setHoveredRow(run.id)}
                    onMouseLeave={() => setHoveredRow(null)}
                    style={{
                      background: run.is_baseline
                        ? "rgba(167,139,250,0.05)"
                        : hoveredRow === run.id
                        ? "rgba(124,58,237,0.04)"
                        : "transparent",
                      transition: "background 0.15s",
                    }}
                  >
                    {/* Pin button */}
                    <td style={{ ...TD, padding: "11px 6px", width: 32, textAlign: "center" }}>
                      {run.status === "done" && (
                        <PinButton
                          active={run.is_baseline}
                          onClick={() => void onSetBaseline(run.id)}
                        />
                      )}
                    </td>

                    {/* ID + baseline badge */}
                    <td
                      style={{
                        ...TD,
                        fontFamily:
                          "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                        fontSize: 11,
                      }}
                    >
                      <Tip text={run.id}>{run.id.slice(0, 8)}…</Tip>
                      {run.is_baseline && <BaselineBadge />}
                    </td>

                    {/* URL */}
                    <td style={{ ...TD, maxWidth: 200 }}>
                      <Tip text={run.target_url}>
                        <span
                          style={{
                            display: "block",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            maxWidth: 200,
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

                    {/* Method */}
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

                    {/* Run status */}
                    <td style={TD}>
                      <StatusBadge status={run.status} />
                    </td>

                    {/* SLA badge */}
                    <td style={TD}>
                      {slaStatus != null && (
                        <SlaBadge
                          status={slaStatus}
                          onClick={() => toggleSla(run.id)}
                        />
                      )}
                    </td>

                    {/* p50 + delta */}
                    <td
                      style={{
                        ...TD,
                        fontFamily:
                          "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                        color: "#10b981",
                      }}
                    >
                      {fmt(run.metrics?.p50)}
                      {run.delta_p50_pct !== undefined && (
                        <DeltaChip value={run.delta_p50_pct} />
                      )}
                    </td>

                    {/* p95 + delta */}
                    <td
                      style={{
                        ...TD,
                        fontFamily:
                          "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                        color: "#f59e0b",
                      }}
                    >
                      {fmt(run.metrics?.p95)}
                      {run.delta_p95_pct !== undefined && (
                        <DeltaChip value={run.delta_p95_pct} />
                      )}
                    </td>

                    {/* p99 + delta */}
                    <td
                      style={{
                        ...TD,
                        fontFamily:
                          "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
                        color: "#ef4444",
                      }}
                    >
                      {fmt(run.metrics?.p99)}
                      {run.delta_p99_pct !== undefined && (
                        <DeltaChip value={run.delta_p99_pct} />
                      )}
                    </td>

                    {/* When */}
                    <td style={{ ...TD, color: "#8892b0", fontSize: 12 }}>
                      {relativeTime(run.created_at)}
                    </td>
                  </tr>

                  {/* Expandable SLA breakdown — rendered below the run row */}
                  {slaExpanded && run.sla_result && run.sla_result.thresholds.length > 0 && (
                    <SlaBreakdownRow
                      thresholds={run.sla_result.thresholds}
                      colSpan={COL_COUNT}
                    />
                  )}
                </Fragment>
              );
            })}
            {runs.length === 0 && (
              <tr>
                <td
                  colSpan={COL_COUNT}
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
