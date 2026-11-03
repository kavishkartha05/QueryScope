#!/usr/bin/env node
/**
 * QueryScope MCP Server
 *
 * MCP (Model Context Protocol) lets AI assistants call tools defined here as
 * if they were functions. The server communicates over stdio: the host process
 * (e.g. Claude Desktop) spawns this script and exchanges JSON-RPC messages
 * over stdin/stdout. Each registered tool appears as a callable function in
 * the assistant's context.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import axios from "axios";
import { z } from "zod";

// Where the backend lives. Defaults to a local stack; set QUERYSCOPE_URL for a
// hosted deployment (no trailing slash needed).
const BACKEND = (process.env.QUERYSCOPE_URL || "http://localhost:8000").replace(/\/+$/, "");

// Optional access code for a hosted (auth-enabled) deployment. With no code set
// the server behaves exactly as before and sends no Authorization header.
const ACCESS_CODE = process.env.QUERYSCOPE_ACCESS_CODE || "";

// Server-side caps on the hosted demo. Mirrored here so a bad request fails
// with a clear message before it leaves the machine.
const MAX_REQUESTS = 500;
const MAX_CONCURRENCY = 20;
const MAX_TIMEOUT_S = 10;

let token: string | null = null;
let loginInFlight: Promise<void> | null = null;

/** Exchange the access code for a token. Never logs the code or the token. */
async function login(): Promise<void> {
  if (!ACCESS_CODE) return;
  try {
    const res = await axios.post<{ token: string }>(`${BACKEND}/auth/login`, { code: ACCESS_CODE });
    token = res.data.token;
  } catch (err) {
    // 404 means the server has auth disabled: carry on without a token.
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      token = null;
      return;
    }
    const status = axios.isAxiosError(err) ? err.response?.status : undefined;
    throw new Error(
      status === 401
        ? "QueryScope rejected the access code in QUERYSCOPE_ACCESS_CODE"
        : "Could not log in to QueryScope"
    );
  }
}

// Concurrent tool calls share one login instead of each starting their own.
function ensureLogin(): Promise<void> {
  if (loginInFlight === null) {
    loginInFlight = login().finally(() => {
      loginInFlight = null;
    });
  }
  return loginInFlight;
}

const api = axios.create({ baseURL: BACKEND });

api.interceptors.request.use(async (config) => {
  if (ACCESS_CODE && token === null) await ensureLogin();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Tokens expire (12 h by default) and revoked codes stop working: on a 401 log
// in again once and retry the request.
api.interceptors.response.use(undefined, async (error) => {
  const original = error.config;
  if (
    ACCESS_CODE &&
    axios.isAxiosError(error) &&
    error.response?.status === 401 &&
    original &&
    !original._retried
  ) {
    original._retried = true;
    token = null;
    await ensureLogin();
    if (token) original.headers.Authorization = `Bearer ${token}`;
    return api.request(original);
  }
  return Promise.reject(error);
});

/** Short, safe text for a failed call (no request bodies, no credentials). */
function describe(err: unknown): string {
  if (axios.isAxiosError(err) && err.response) {
    const detail = typeof err.response.data?.detail === "string" ? err.response.data.detail : "";
    const retry = err.response.headers["retry-after"];
    const wait = retry ? ` Retry after ${retry} s.` : "";
    return `QueryScope returned ${err.response.status}${detail ? ": " + detail : ""}.${wait}`;
  }
  return err instanceof Error ? err.message : "Request failed";
}

const server = new McpServer({
  name: "queryscope-mcp",
  version: "0.1.0",
});

// ---------------------------------------------------------------------------
// Tool: run_benchmark
// ---------------------------------------------------------------------------

server.registerTool(
  "run_benchmark",
  {
    description: "Run a load benchmark against an API endpoint",
    inputSchema: {
      target_url: z.string().url().describe("The URL to benchmark"),
      method: z.string().default("GET").describe("HTTP method (GET, POST, etc.)"),
      num_requests: z.number().int().min(1).max(MAX_REQUESTS).default(20).describe(`Total requests to send (max ${MAX_REQUESTS})`),
      concurrency: z.number().int().min(1).max(MAX_CONCURRENCY).default(5).describe(`Concurrent requests in flight (max ${MAX_CONCURRENCY})`),
      timeout_s: z.number().positive().max(MAX_TIMEOUT_S).default(MAX_TIMEOUT_S).describe(`Per-request timeout in seconds (max ${MAX_TIMEOUT_S})`),
    },
  },
  async ({ target_url, method, num_requests, concurrency, timeout_s }) => {
    let run_id: string;
    try {
      const res = await api.post<{ run_id: string }>("/benchmark", {
        target_url,
        method,
        num_requests,
        concurrency,
        timeout_s,
      });
      run_id = res.data.run_id;
    } catch (err) {
      return { isError: true, content: [{ type: "text" as const, text: describe(err) }] };
    }

    return {
      content: [
        {
          type: "text" as const,
          text: `Benchmark started. Run ID: ${run_id}`,
        },
      ],
    };
  }
);

// ---------------------------------------------------------------------------
// Tool: query_runs
// ---------------------------------------------------------------------------

interface MetricsSummary {
  p50: number;
  p95: number;
  p99: number;
}

interface Run {
  id: string;
  target_url: string;
  method: string;
  status: string;
  metrics: MetricsSummary | null;
}

interface PaginatedRuns {
  items: Run[];
  total: number;
}

server.registerTool(
  "query_runs",
  {
    description: "List recent benchmark runs with their latency metrics",
    inputSchema: {
      limit: z.number().int().min(1).max(100).default(10).describe("Number of runs to return"),
    },
  },
  async ({ limit }) => {
    let res;
    try {
      res = await api.get<PaginatedRuns>("/benchmark/runs", { params: { limit } });
    } catch (err) {
      return { isError: true, content: [{ type: "text" as const, text: describe(err) }] };
    }

    const { items, total } = res.data;

    if (items.length === 0) {
      return {
        content: [{ type: "text" as const, text: "No benchmark runs found." }],
      };
    }

    // Format each run as a compact summary line for easy reading by the LLM.
    const lines: string[] = [];
    for (const run of items) {
      const p50 = run.metrics ? `${run.metrics.p50.toFixed(1)}ms` : "-";
      const p95 = run.metrics ? `${run.metrics.p95.toFixed(1)}ms` : "-";
      const p99 = run.metrics ? `${run.metrics.p99.toFixed(1)}ms` : "-";
      lines.push(
        `[${run.id.slice(0, 8)}] ${run.method} ${run.target_url} ` +
          `status=${run.status} p50=${p50} p95=${p95} p99=${p99}`
      );
    }

    const text = `${total} total run(s). Showing ${items.length}:\n\n${lines.join("\n")}`;

    return {
      content: [{ type: "text" as const, text }],
    };
  }
);

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

async function main() {
  // StdioServerTransport reads from process.stdin and writes to process.stdout.
  // All logging must go to stderr to avoid corrupting the JSON-RPC framing on stdout.
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write("QueryScope MCP server running on stdio\n");
}

main().catch((err) => {
  process.stderr.write(`Fatal: ${err}\n`);
  process.exit(1);
});
