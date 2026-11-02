import { useEffect, useRef, useState } from "react";
import client from "./api/client";
import { fetchConfig, getBoot, loginWithCode } from "./api/auth";
import { describeError } from "./api/errors";
import { clearSession, getLabel, setUnauthorizedListener } from "./api/session";
import BenchmarkForm from "./components/BenchmarkForm";
import DiagnosePanel from "./components/DiagnosePanel";
import Landing from "./components/Landing";
import LatencyChart from "./components/LatencyChart";
import RunsTable from "./components/RunsTable";
import type { AppConfig } from "./types/config";
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

function Navbar({
  connected,
  label,
  onSignOut,
}: {
  connected: boolean | null;
  label: string | null;
  onSignOut: (() => void) | null;
}) {
  const dot = connected === null ? "#6b7280" : connected ? "#10b981" : "#ef4444";
  const text = connected === null ? "Connecting…" : connected ? "API connected" : "API disconnected";
  return (
    <nav
      className="qs-nav"
      aria-label="Main"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
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

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span role="status" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            aria-hidden
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: dot,
              boxShadow: connected === null ? "none" : `0 0 7px ${dot}`,
              display: "inline-block",
            }}
          />
          <span className="qs-hide-mobile" style={{ fontSize: 12, color: "#8892b0" }}>
            {text}
          </span>
          <span className="qs-visually-hidden">{text}</span>
        </span>
        {label && (
          <span className="qs-hide-mobile" style={{ fontSize: 12, color: "#8892b0" }}>
            {label}
          </span>
        )}
        {onSignOut && (
          <button
            type="button"
            onClick={onSignOut}
            style={{
              padding: "4px 12px",
              background: "transparent",
              border: "1px solid #2e3150",
              borderRadius: 6,
              color: "#ccd6f6",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Sign out
          </button>
        )}
      </div>
    </nav>
  );
}

// ── Card ───────────────────────────────────────────────────────────────────

function Card({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <section
      className="qs-card"
      aria-label={label}
      style={{
        background: "#0f0f1a",
        border: "1px solid #1a1a2e",
        borderRadius: 12,
        position: "relative",
        zIndex: 1,
      }}
    >
      {children}
    </section>
  );
}

// ── Dashboard (signed in) ──────────────────────────────────────────────────

const POLL_MS = 3000;

function Dashboard({
  config,
  label,
  onSignOut,
}: {
  config: AppConfig;
  label: string | null;
  onSignOut: () => void;
}) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [total, setTotal] = useState(0);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [visible, setVisible] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchRuns() {
    try {
      const res = await client.get<PaginatedRuns>("/benchmark/runs");
      setRuns(res.data.items);
      setTotal(res.data.total);
      setFetchError(null);
      setConnected(true);
    } catch (err: unknown) {
      // A 401 is handled globally (back to the landing page); show the rest.
      setFetchError(describeError(err));
      setConnected(false);
    }
  }

  useEffect(() => {
    // Fetch on mount; the state updates happen after the request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchRuns();
    intervalRef.current = setInterval(() => {
      // No point polling a tab nobody is looking at.
      if (!document.hidden) void fetchRuns();
    }, POLL_MS);
    requestAnimationFrame(() => setVisible(true));
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  async function handleSetBaseline(runId: string) {
    setActionError(null);
    try {
      await client.patch(`/benchmark/runs/${runId}/baseline`);
      // Refresh now so the new baseline and every delta render without
      // waiting for the next poll.
      await fetchRuns();
    } catch (err: unknown) {
      setActionError(describeError(err));
    }
  }

  async function handleClearBaseline() {
    setActionError(null);
    try {
      await client.delete("/benchmark/runs/baseline");
      await fetchRuns();
    } catch (err: unknown) {
      setActionError(describeError(err));
    }
  }

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0f" }}>
      <MouseGlow />
      <Navbar connected={connected} label={label} onSignOut={config.auth_enabled ? onSignOut : null} />

      <main
        className="qs-main"
        style={{
          maxWidth: 980,
          margin: "0 auto",
          display: "flex",
          flexDirection: "column",
          gap: 24,
          opacity: visible ? 1 : 0,
          transform: visible ? "translateY(0)" : "translateY(14px)",
          transition: "opacity 0.5s ease, transform 0.5s ease",
        }}
      >
        <Card label="New benchmark">
          <BenchmarkForm config={config} onRunCreated={() => void fetchRuns()} />
        </Card>

        <Card label="Benchmark runs">
          <RunsTable
            runs={runs}
            total={total}
            error={fetchError ?? actionError}
            onSetBaseline={handleSetBaseline}
            onClearBaseline={handleClearBaseline}
          />
        </Card>

        <Card label="Latency chart">
          <LatencyChart runs={runs} />
        </Card>

        <Card label="Diagnose">
          <DiagnosePanel />
        </Card>
      </main>
    </div>
  );
}

// ── App: decides between loading, landing and dashboard ────────────────────

type View =
  | { kind: "loading" }
  | { kind: "landing"; notice: string | null }
  | { kind: "dashboard"; config: AppConfig };

export default function App() {
  const [view, setView] = useState<View>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    void getBoot().then((result) => {
      if (cancelled) return;
      if (result.kind === "authed") setView({ kind: "dashboard", config: result.config });
      else setView({ kind: "landing", notice: result.message });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Any 401 after load (expired or revoked) returns to the landing page.
  useEffect(() => {
    setUnauthorizedListener(() => {
      setView({
        kind: "landing",
        notice: "Your session has expired or was revoked. Enter your access code to continue.",
      });
    });
    return () => setUnauthorizedListener(null);
  }, []);

  async function handleLogin(code: string): Promise<string | null> {
    const failure = await loginWithCode(code);
    if (failure !== null) return failure;
    const result = await fetchConfig();
    if (result.kind === "authed") {
      setView({ kind: "dashboard", config: result.config });
      return null;
    }
    return result.message ?? "Could not start your session. Please try again.";
  }

  function handleSignOut() {
    clearSession();
    setView({ kind: "landing", notice: null });
  }

  if (view.kind === "loading") {
    return (
      <div role="status" style={{ minHeight: "100vh", background: "#0a0a0f", color: "#8892b0", display: "grid", placeItems: "center" }}>
        Loading…
      </div>
    );
  }
  if (view.kind === "landing") {
    return <Landing notice={view.notice} onLogin={handleLogin} />;
  }
  return <Dashboard config={view.config} label={getLabel()} onSignOut={handleSignOut} />;
}
