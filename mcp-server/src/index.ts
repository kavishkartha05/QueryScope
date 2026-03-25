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

const BACKEND = "http://localhost:8000";

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
      method: z.string().default("GET").describe("HTTP method (GET, POST, …)"),
      num_requests: z.number().int().min(1).default(20).describe("Total requests to send"),
      concurrency: z.number().int().min(1).default(5).describe("Concurrent requests in flight"),
    },
  },
  async ({ target_url, method, num_requests, concurrency }) => {
    const res = await axios.post<{ run_id: string }>(`${BACKEND}/benchmark`, {
      target_url,
      method,
      num_requests,
      concurrency,
    });

    const { run_id } = res.data;

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
    const res = await axios.get<PaginatedRuns>(`${BACKEND}/benchmark/runs`, {
      params: { limit },
    });

    const { items, total } = res.data;

    if (items.length === 0) {
      return {
        content: [{ type: "text" as const, text: "No benchmark runs found." }],
      };
    }

    // Format each run as a compact summary line for easy reading by the LLM.
    const lines = items.map((run) => {
      const p50 = run.metrics ? `${run.metrics.p50.toFixed(1)}ms` : "—";
      const p95 = run.metrics ? `${run.metrics.p95.toFixed(1)}ms` : "—";
      const p99 = run.metrics ? `${run.metrics.p99.toFixed(1)}ms` : "—";
      return (
        `[${run.id.slice(0, 8)}] ${run.method} ${run.target_url} ` +
        `status=${run.status} p50=${p50} p95=${p95} p99=${p99}`
      );
    });

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
