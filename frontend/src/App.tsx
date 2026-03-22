import { useEffect, useState } from "react";
import client from "./api/client";
import BenchmarkForm from "./components/BenchmarkForm";
import DiagnosePanel from "./components/DiagnosePanel";
import LatencyChart from "./components/LatencyChart";
import RunsTable from "./components/RunsTable";
import type { PaginatedRuns, Run } from "./types/run";

export default function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [total, setTotal] = useState(0);
  const [fetchError, setFetchError] = useState<string | null>(null);

  async function fetchRuns() {
    try {
      const res = await client.get<PaginatedRuns>("/benchmark/runs");
      setRuns(res.data.items);
      setTotal(res.data.total);
      setFetchError(null);
    } catch (err: unknown) {
      setFetchError(err instanceof Error ? err.message : "Failed to fetch runs");
    }
  }

  useEffect(() => {
    void fetchRuns();
    // Polling lives here so RunsTable and LatencyChart share one fetch cycle
    // rather than each component making independent requests.
    const id = setInterval(() => void fetchRuns(), 3000);
    return () => clearInterval(id);
  }, []);

  function handleRunCreated(_runId: string) {
    // Fetch immediately so the new "pending" row appears without waiting for
    // the next poll tick.
    void fetchRuns();
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "340px 1fr",
        gap: 32,
        padding: 32,
        fontFamily: "system-ui, sans-serif",
        maxWidth: 1200,
        margin: "0 auto",
      }}
    >
      <aside>
        <BenchmarkForm onRunCreated={handleRunCreated} />
      </aside>
      <main style={{ display: "flex", flexDirection: "column", gap: 32 }}>
        <RunsTable runs={runs} total={total} error={fetchError} />
        <section>
          <h2>Latency Chart</h2>
          <LatencyChart runs={runs} />
        </section>
        <section>
          <DiagnosePanel />
        </section>
      </main>
    </div>
  );
}
