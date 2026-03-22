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
  created_at: string;
  metrics: MetricsSummary | null;
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
