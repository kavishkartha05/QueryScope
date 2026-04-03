export type RunStatus = "pending" | "running" | "done" | "failed";

export interface MetricsSummary {
  p50: number;
  p95: number;
  p99: number;
  throughput: number;
  error_rate: number;
}

export interface MetricsDetail extends MetricsSummary {
  id: string;
  run_id: string;
  latencies: number[];
}

export interface Run {
  id: string;
  target_url: string;
  method: string;
  num_requests: number;
  concurrency: number;
  status: RunStatus;
  is_baseline: boolean;
  created_at: string;
  // Absent (undefined) when the run has not completed yet.
  // response_model_exclude_none=True on the list endpoint omits the field
  // rather than returning null, so we use optional here.
  metrics?: MetricsSummary | null;
  // Delta fields — only present on non-baseline runs when a baseline is pinned.
  delta_p50_pct?: number;
  delta_p95_pct?: number;
  delta_p99_pct?: number;
  delta_avg_latency_pct?: number;
  delta_error_rate_pct?: number;
}

export interface PaginatedRuns {
  total: number;
  offset: number;
  limit: number;
  items: Run[];
}

export interface BenchmarkRequest {
  target_url: string;
  method: string;
  num_requests: number;
  concurrency: number;
  headers?: Record<string, string>;
  body?: Record<string, unknown>;
}

export interface RunCreatedResponse {
  run_id: string;
}

export interface DiagnoseResponse {
  diagnosis: string;
}
