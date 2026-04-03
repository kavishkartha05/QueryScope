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
  // SLA — absent when no thresholds were configured for the run.
  sla_config?: SlaConfig;
  sla_result?: SlaResult;
}

export interface PaginatedRuns {
  total: number;
  offset: number;
  limit: number;
  items: Run[];
}

export interface SlaConfig {
  p50_ms?: number | null;
  p95_ms?: number | null;
  p99_ms?: number | null;
  avg_latency_ms?: number | null;
  error_rate_pct?: number | null;
}

export interface SlaThresholdResult {
  metric: string;
  target: number;
  actual: number;
  status: "pass" | "fail";
  delta: number;
}

export interface SlaResult {
  status: "pass" | "fail" | null;
  thresholds: SlaThresholdResult[];
}

export interface BenchmarkRequest {
  target_url: string;
  method: string;
  num_requests: number;
  concurrency: number;
  headers?: Record<string, string>;
  body?: Record<string, unknown>;
  sla_p50_ms?: number;
  sla_p95_ms?: number;
  sla_p99_ms?: number;
  sla_avg_latency_ms?: number;
  sla_error_rate_pct?: number;
}

export interface RunCreatedResponse {
  run_id: string;
}

export interface DiagnoseResponse {
  diagnosis: string;
}
