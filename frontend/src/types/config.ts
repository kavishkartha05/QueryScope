export interface TargetOption {
  label: string;
  url: string;
}

export interface AppConfig {
  caps: {
    max_num_requests: number;
    max_concurrency: number;
    max_request_timeout_s: number;
    run_wall_clock_limit_s: number;
  };
  targets: TargetOption[];
  allow_custom_target: boolean;
  llm_benchmark_enabled: boolean;
  auth_enabled: boolean;
}
