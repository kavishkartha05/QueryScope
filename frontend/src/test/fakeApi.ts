import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { AxiosError } from "axios";
import client from "../api/client";

export interface FakeReply {
  status: number;
  data?: unknown;
  headers?: Record<string, string>;
}
export type Handler = (config: InternalAxiosRequestConfig) => FakeReply;

// Replace the network with a function; non-2xx replies reject like real axios.
export function installFakeApi(handler: Handler): InternalAxiosRequestConfig[] {
  const seen: InternalAxiosRequestConfig[] = [];
  const adapter: AxiosAdapter = (config) => {
    seen.push(config);
    const reply = handler(config);
    const response: AxiosResponse = {
      status: reply.status,
      statusText: String(reply.status),
      data: reply.data ?? {},
      headers: reply.headers ?? {},
      config,
    };
    if (reply.status >= 200 && reply.status < 300) return Promise.resolve(response);
    return Promise.reject(new AxiosError("failed", String(reply.status), config, null, response));
  };
  client.defaults.adapter = adapter;
  return seen;
}

export const CONFIG = {
  caps: { max_num_requests: 500, max_concurrency: 20, max_request_timeout_s: 10, run_wall_clock_limit_s: 60 },
  targets: [
    { label: "httpbin.org", url: "https://httpbin.org/get" },
    { label: "QueryScope demo target", url: "https://demo.example.com/work" },
  ],
  allow_custom_target: false,
  llm_benchmark_enabled: false,
  auth_enabled: true,
};
