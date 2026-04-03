import { useEffect, useRef, useState } from "react";
import client from "./api/client";
import BenchmarkForm from "./components/BenchmarkForm";
import DiagnosePanel from "./components/DiagnosePanel";
import LatencyChart from "./components/LatencyChart";
import RunsTable from "./components/RunsTable";
import type { PaginatedRuns, Run } from "./types/run";

// ── Mouse-follow glow ──────────────────────────────────────────────────────

function MouseGlow() {
  const [pos, setPos] = useState({ x: -999, y: -999 });

  useEffect(() => {
    function onMove(e: MouseEvent) {
      setPos({ x: e.clientX, y: e.clientY });
    }
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, []);

  return (
    <div
      aria-hidden
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        width: 700,
        height: 700,
        borderRadius: "50%",
        background:
          "radial-gradient(circle at center, rgba(124,58,237,0.06) 0%, transparent 65%)",
        transform: `translate(${pos.x - 350}px, ${pos.y - 350}px)`,
        pointerEvents: "none",
        zIndex: 0,
        transition: "transform 0.08s linear",
      }}
    />
  );
}

// ── Navbar ─────────────────────────────────────────────────────────────────

function Navbar({ connected }: { connected: boolean | null }) {
  return (
    <nav
      style={{
        position: "sticky",
        top: 0,
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 32px",
        height: 54,
        background: "rgba(10,10,15,0.88)",
        backdropFilter: "blur(14px)",
        borderBottom: "1px solid #1a1a2e",
      }}
    >
      <span
        style={{
          fontFamily: "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
          fontWeight: 700,
          fontSize: 16,
          color: "#e6f1ff",
          letterSpacing: "0.02em",
        }}
      >
        QueryScope
      </span>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background:
              connected === null
                ? "#6b7280"
                : connected
                ? "#10b981"
                : "#ef4444",
            boxShadow:
              connected === true
                ? "0 0 7px #10b981"
                : connected === false
                ? "0 0 7px #ef4444"
                : "none",
            transition: "background 0.3s, box-shadow 0.3s",
            display: "inline-block",
          }}
        />
        <span
          style={{
            fontSize: 12,
            color: "#8892b0",
            letterSpacing: "0.03em",
          }}
        >
          {connected === null
            ? "Connecting…"
            : connected
            ? "API Connected"
            : "API Disconnected"}
        </span>
      </div>
    </nav>
  );
}

// ── Card ───────────────────────────────────────────────────────────────────

function Card({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        background: "#0f0f1a",
        border: "1px solid #1a1a2e",
        borderRadius: 12,
        padding: "28px 32px",
        position: "relative",
        zIndex: 1,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ── App ────────────────────────────────────────────────────────────────────

export default function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [total, setTotal] = useState(0);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [visible, setVisible] = useState(false);
  const [formResetKey, setFormResetKey] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchRuns() {
    try {
      const res = await client.get<PaginatedRuns>("/benchmark/runs");
      setRuns(res.data.items);
      setTotal(res.data.total);
      setFetchError(null);
      setConnected(true);
    } catch (err: unknown) {
      setFetchError(err instanceof Error ? err.message : "Failed to fetch runs");
      setConnected(false);
    }
  }

  useEffect(() => {
    void fetchRuns();
    intervalRef.current = setInterval(() => void fetchRuns(), 3000);
    requestAnimationFrame(() => setVisible(true));
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  function handleRunCreated(_runId: string) {
    void fetchRuns();
  }

  async function handleReset() {
    await client.delete("/benchmark/runs");
    // Clear state immediately so the table and chart empty before the next
    // poll cycle fires — avoids a brief flash of stale data.
    setRuns([]);
    setTotal(0);
    // Incrementing the key signals BenchmarkForm to clear its SLA fields.
    setFormResetKey((k) => k + 1);
  }

  async function handleSetBaseline(runId: string) {
    await client.patch(`/benchmark/runs/${runId}/baseline`);
    // Refresh immediately so the new baseline and all deltas render without
    // waiting for the next 3-second poll cycle.
    void fetchRuns();
  }

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0f" }}>
      <MouseGlow />
      <Navbar connected={connected} />

      <main
        style={{
          maxWidth: 980,
          margin: "0 auto",
          padding: "36px 24px 96px",
          display: "flex",
          flexDirection: "column",
          gap: 24,
          opacity: visible ? 1 : 0,
          transform: visible ? "translateY(0)" : "translateY(14px)",
          transition: "opacity 0.5s ease, transform 0.5s ease",
        }}
      >
        <Card>
          <BenchmarkForm onRunCreated={handleRunCreated} resetKey={formResetKey} />
        </Card>

        <Card>
          <RunsTable runs={runs} total={total} error={fetchError} onReset={handleReset} onSetBaseline={handleSetBaseline} />
        </Card>

        <Card>
          <LatencyChart runs={runs} />
        </Card>

        <Card>
          <DiagnosePanel />
        </Card>
      </main>
    </div>
  );
}
