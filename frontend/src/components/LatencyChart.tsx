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
  id: string;
  p50: number;
  p95: number;
  p99: number;
}

export default function LatencyChart({ runs }: LatencyChartProps) {
  const data: ChartRow[] = runs
    .filter((r) => r.status === "done" && r.metrics !== null)
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => ({
      id: r.id.slice(0, 8),
      // Non-null assertion safe: filter above guarantees metrics exists.
      p50: r.metrics!.p50,
      p95: r.metrics!.p95,
      p99: r.metrics!.p99,
    }));

  const heading = (
    <h2
      style={{
        margin: "0 0 20px",
        fontSize: 13,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.1em",
        color: "#8892b0",
      }}
    >
      Latency Distribution
    </h2>
  );

  if (data.length === 0) {
    return (
      <>
        {heading}
        <div
          style={{
            height: 200,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#8892b0",
            fontSize: 13,
            border: "1px dashed #1a1a2e",
            borderRadius: 8,
          }}
        >
          No completed runs yet
        </div>
      </>
    );
  }

  return (
    <>
      {heading}
      <ResponsiveContainer width="100%" height={400}>
        <BarChart
          data={data}
          margin={{ top: 8, right: 24, bottom: 8, left: 8 }}
          barCategoryGap="30%"
        >
          <CartesianGrid
            strokeDasharray="3 3"
            vertical={false}
            stroke="#1a1a2e"
          />
          <XAxis
            dataKey="id"
            tick={{
              fontFamily:
                "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
              fontSize: 11,
              fill: "#8892b0",
            }}
            axisLine={{ stroke: "#1a1a2e" }}
            tickLine={false}
          />
          <YAxis
            unit=" ms"
            tick={{ fontSize: 11, fill: "#8892b0" }}
            axisLine={false}
            tickLine={false}
            domain={[0, "auto"]}
          />
          <Tooltip
            contentStyle={{
              background: "#13131f",
              border: "1px solid #2a2a40",
              borderRadius: 8,
              fontSize: 12,
              fontFamily:
                "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
              color: "#ccd6f6",
            }}
            cursor={{ fill: "rgba(124,58,237,0.04)" }}
            formatter={(value: unknown) => [`${Number(value).toFixed(1)} ms`, ``]}
          />
          <Legend
            wrapperStyle={{
              fontSize: 11,
              fontFamily:
                "ui-monospace, SFMono-Regular, Fira Code, Consolas, monospace",
              color: "#8892b0",
              paddingTop: 16,
            }}
          />
          <Bar dataKey="p50" name="p50" fill="#10b981" radius={[4, 4, 0, 0]} isAnimationActive />
          <Bar dataKey="p95" name="p95" fill="#f59e0b" radius={[4, 4, 0, 0]} isAnimationActive />
          <Bar dataKey="p99" name="p99" fill="#ef4444" radius={[4, 4, 0, 0]} isAnimationActive />
        </BarChart>
      </ResponsiveContainer>
    </>
  );
}
