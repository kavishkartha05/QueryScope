import { useRef } from "react";
import BenchmarkForm from "./components/BenchmarkForm";
import RunsTable from "./components/RunsTable";

export default function App() {
  // tableKey forces RunsTable to remount (and immediately re-fetch) when a
  // new run is submitted, so the new "pending" row appears without waiting
  // for the next 3-second poll interval.
  const tableKey = useRef(0);

  function handleRunCreated(_runId: string) {
    tableKey.current += 1;
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
      <main>
        <RunsTable key={tableKey.current} />
      </main>
    </div>
  );
}
