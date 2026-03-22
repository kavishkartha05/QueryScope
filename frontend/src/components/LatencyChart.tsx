import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Run } from "../types/run";

interface LatencyChartProps {
  runs: Run[];
}

interface ChartRow {
  id: string;   // truncated run ID used as X-axis tick
  p50: number;
  p95: number;
  p99: number;
}

export default function LatencyChart({ runs }: LatencyChartProps) {
  const data: ChartRow[] = runs
    .filter((r) => r.status === "done" && r.metrics !== null)
    .map((r) => ({
      id: r.id.slice(0, 8),
      // Non-null assertion is safe: filter above guarantees metrics exists.
      p50: r.metrics!.p50,
      p95: r.metrics!.p95,
      p99: r.metrics!.p99,
    }));

  if (data.length === 0) {
    return (
      <div style={{ padding: "24px 0", color: "#888", textAlign: "center" }}>
        No completed runs yet.
      </div>
    );
  }

  return (
    // ResponsiveContainer fills the parent width; fixed height keeps the
    // chart readable without needing the parent to define a pixel height.
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="id" tick={{ fontFamily: "monospace", fontSize: 12 }} />
        <YAxis
          unit=" ms"
          tick={{ fontSize: 12 }}
          // Start at 0 so bars are visually comparable across runs.
          domain={[0, "auto"]}
        />
        <Tooltip
          formatter={(value: number, name: string) => [`${value.toFixed(2)} ms`, name]}
          labelFormatter={(label: string) => `Run ${label}`}
        />
        <Legend />
        <Bar dataKey="p50" name="p50" fill="#2e7d32" radius={[3, 3, 0, 0]} />
        <Bar dataKey="p95" name="p95" fill="#d4a017" radius={[3, 3, 0, 0]} />
        <Bar dataKey="p99" name="p99" fill="#c62828" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
