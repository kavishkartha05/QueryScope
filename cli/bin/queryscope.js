#!/usr/bin/env node
/**
 * queryscope CLI
 *
 * Commands:
 *   queryscope init   — first-time setup: prompts for secrets, writes .env,
 *                       builds + starts the Docker stack, creates Azure index
 *   queryscope start  — start the stack (assumes .env already exists)
 *   queryscope reset  — delete all benchmark runs via the API
 */

import chalk from "chalk";
import ora from "ora";
import { execa } from "execa";
import { writeFileSync, existsSync, readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

// enquirer's default export is the Enquirer class; named `prompt` lives on it.
// We import the class and call prompt() as a static-style helper via new instance.
import Enquirer from "enquirer";

const __dirname = dirname(fileURLToPath(import.meta.url));

// cli/bin/queryscope.js → go up two levels to reach the project root
const ROOT = resolve(__dirname, "../..");
const ENV_PATH = resolve(ROOT, "backend", ".env");

// Read version once at startup so banner and help text stay in sync.
const pkg = JSON.parse(readFileSync(resolve(__dirname, "../package.json"), "utf8"));

// ── Banner ─────────────────────────────────────────────────────────────────

const ASCII_ART = `
  ██████  ██    ██ ███████ ██████  ██    ██ ███████  ██████  ██████   ███████  ███████
 ██    ██ ██    ██ ██      ██   ██  ██  ██  ██      ██      ██    ██  ██    ██ ██
 ██    ██ ██    ██ █████   ██████    ████   ███████ ██      ██    ██  ███████  █████  
 ██ ▄▄ ██ ██    ██ ██      ██   ██    ██         ██ ██      ██    ██  ██       ██
    ████   ██████  ███████ ██   ██    ██    ███████  ██████  ██████   ██       ███████`;

function printBanner() {
  console.log(chalk.green(ASCII_ART));

  // Right-align the version tag to the width of the widest ASCII art line.
  const artWidth = Math.max(...ASCII_ART.split("\n").map((l) => l.length));
  const version = `v${pkg.version}`;
  console.log(chalk.dim.green(version.padStart(artWidth)));

  console.log(
    chalk.dim("\n  Load testing + AI diagnosis for REST & LLM endpoints\n")
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────

/** Run a shell command in ROOT, streaming stdout/stderr to the terminal. */
async function run(file, args, opts = {}) {
  return execa(file, args, { cwd: ROOT, stdio: "inherit", ...opts });
}

/** Run a shell command in ROOT, capturing output (no terminal passthrough). */
async function capture(file, args, opts = {}) {
  return execa(file, args, { cwd: ROOT, stdio: "pipe", ...opts });
}

/** Print a formatted error and exit with code 1. */
function fatal(msg) {
  console.error(chalk.red(`\n  error  `) + msg);
  process.exit(1);
}

// ── Commands ───────────────────────────────────────────────────────────────

async function cmdInit() {
  printBanner();

  // ── Check Docker ────────────────────────────────────────────────────────
  const dockerSpinner = ora("Checking Docker…").start();
  try {
    await capture("docker", ["info"]);
    dockerSpinner.succeed("Docker is running");
  } catch {
    dockerSpinner.fail("Docker is not running");
    console.error(
      chalk.yellow(
        "\n  Please start Docker Desktop (or the Docker daemon) and re-run:\n" +
        chalk.bold("    queryscope init\n")
      )
    );
    process.exit(1);
  }

  // ── Collect secrets ─────────────────────────────────────────────────────
  console.log(chalk.dim("\n  Enter your credentials (keys are hidden):\n"));

  const enquirer = new Enquirer();

  // enquirer's `password` type masks the value with asterisks.
  const { openaiKey } = await enquirer.prompt({
    type: "password",
    name: "openaiKey",
    message: "OpenAI API key",
  });

  const { azureEndpoint } = await enquirer.prompt({
    type: "input",
    name: "azureEndpoint",
    message: "Azure Search endpoint",
    hint: "https://<your-resource>.search.windows.net",
    validate: (v) =>
      v.startsWith("https://") ? true : "Must start with https://",
  });

  const { azureKey } = await enquirer.prompt({
    type: "password",
    name: "azureKey",
    message: "Azure Search admin key",
  });

  // ── Write backend/.env ──────────────────────────────────────────────────
  // DATABASE_URL is set via docker-compose environment: override, so the
  // value here is only used for local (non-Docker) development.
  const envContent = [
    `DATABASE_URL=postgresql+asyncpg://queryscope:queryscope@postgres:5432/queryscope`,
    `APP_NAME=QueryScope`,
    `DEBUG=false`,
    `AZURE_SEARCH_ENDPOINT=${azureEndpoint}`,
    `AZURE_SEARCH_KEY=${azureKey}`,
    `AZURE_SEARCH_INDEX=benchmark-runs`,
    `OPENAI_API_KEY=${openaiKey}`,
    `CORS_ORIGINS=["http://localhost:5173"]`,
  ].join("\n") + "\n";

  writeFileSync(ENV_PATH, envContent, { encoding: "utf8" });
  console.log(chalk.green(`\n  Wrote ${ENV_PATH}`));

  // ── docker compose up --build -d ─────────────────────────────────────────
  console.log("");
  const buildSpinner = ora("Building and starting QueryScope…").start();
  try {
    // Pass stdio:"pipe" so ora owns the terminal; execa errors still surface.
    await capture("docker", ["compose", "up", "--build", "-d"]);
    buildSpinner.succeed("Stack is up");
  } catch (err) {
    buildSpinner.fail("docker compose up failed");
    // Re-run with inherited stdio so the user sees the full build log.
    console.error(chalk.dim("\nRe-running with full output for debugging:\n"));
    await run("docker", ["compose", "up", "--build", "-d"]).catch(() => {});
    fatal("Fix the build error above, then re-run: queryscope init");
  }

  // ── Wait for backend to be healthy, then create the Azure Search index ──
  // Poll /benchmark/runs until the API responds (migrations run at startup).
  const apiSpinner = ora("Waiting for backend to be ready…").start();
  const deadline = Date.now() + 60_000; // 60 s timeout
  let apiReady = false;
  while (Date.now() < deadline) {
    try {
      const res = await fetch("http://localhost:8000/benchmark/runs");
      if (res.ok) { apiReady = true; break; }
    } catch {
      // still starting up — keep polling
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  if (!apiReady) {
    apiSpinner.fail("Backend did not become ready within 60 s");
    fatal("Check logs with: docker compose logs backend");
  }
  apiSpinner.succeed("Backend is ready");

  // Create the Azure AI Search index inside the backend container where the
  // Python env and credentials are already available.
  const indexSpinner = ora("Creating Azure Search index…").start();
  try {
    await capture("docker", [
      "compose", "exec", "backend",
      "poetry", "run", "python", "scripts/create_azure_index.py",
    ]);
    indexSpinner.succeed("Azure Search index ready");
  } catch (err) {
    indexSpinner.fail("Index creation failed");
    // Non-fatal: the index may already exist, or the user may not have Azure
    // configured yet. Print a warning but don't abort setup.
    console.warn(
      chalk.yellow(
        "\n  Warning: could not create Azure Search index.\n" +
        "  If you skipped Azure setup, diagnose queries won't work until\n" +
        "  you run: docker compose exec backend python scripts/create_azure_index.py\n"
      )
    );
  }

  // ── Success ─────────────────────────────────────────────────────────────
  console.log(
    chalk.bold.green("\n  QueryScope is running!\n") +
    chalk.dim("  Dashboard  ") + chalk.cyan("http://localhost:5173") + "\n" +
    chalk.dim("  API        ") + chalk.cyan("http://localhost:8000") + "\n" +
    chalk.dim("  API docs   ") + chalk.cyan("http://localhost:8000/docs") + "\n"
  );
}

async function cmdStart() {
  printBanner();

  // Assumes backend/.env already exists from a previous `queryscope init`.
  if (!existsSync(ENV_PATH)) {
    fatal(
      `${ENV_PATH} not found.\n` +
      `  Run ${chalk.bold("queryscope init")} first to create it.`
    );
  }

  const spinner = ora("Starting QueryScope…").start();
  try {
    await capture("docker", ["compose", "up", "-d"]);
    spinner.succeed("Stack is up");
  } catch {
    spinner.fail("docker compose up failed");
    await run("docker", ["compose", "up", "-d"]).catch(() => {});
    fatal("See output above for details.");
  }

  // Poll until the backend is ready — migrations run at startup so the API
  // may not be immediately available after the containers start.
  const apiSpinner = ora("Waiting for backend to be ready…").start();
  const deadline = Date.now() + 60_000;
  let apiReady = false;
  while (Date.now() < deadline) {
    try {
      const res = await fetch("http://localhost:8000/benchmark/runs");
      if (res.ok) { apiReady = true; break; }
    } catch {
      // still starting up
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  if (!apiReady) {
    apiSpinner.fail("Backend did not become ready within 60 s");
    fatal("Check logs with: docker compose logs backend");
  }
  apiSpinner.succeed("Backend is ready");

  console.log(
    "\n" +
    chalk.dim("  Dashboard  ") + chalk.cyan("http://localhost:5173") + "\n" +
    chalk.dim("  API        ") + chalk.cyan("http://localhost:8000") + "\n"
  );
}

async function cmdReset() {
  // Confirm before destroying data — this is irreversible.
  const enquirer = new Enquirer();
  const { confirmed } = await enquirer.prompt({
    type: "confirm",
    name: "confirmed",
    message: "Reset session? This will delete ALL benchmark runs and metrics.",
    initial: false,
  });

  if (!confirmed) {
    console.log(chalk.dim("  Aborted."));
    return;
  }

  const spinner = ora("Resetting session…").start();
  try {
    const res = await fetch("http://localhost:8000/benchmark/runs", {
      method: "DELETE",
    });
    if (!res.ok) {
      const body = await res.text();
      spinner.fail("API returned an error");
      fatal(`${res.status} ${body}`);
    }
    const data = await res.json();
    spinner.succeed(data.message ?? "Session reset");
  } catch (err) {
    spinner.fail("Request failed");
    fatal(
      "Could not reach the API. Is the stack running?\n" +
      `  Try: ${chalk.bold("queryscope start")}`
    );
  }
}

// ── Router ─────────────────────────────────────────────────────────────────

const command = process.argv[2];

const HELP = `
${chalk.bold("queryscope")} — QueryScope CLI

${chalk.bold("Usage:")}
  queryscope ${chalk.cyan("init")}    First-time setup: configure secrets, build, and start the stack
  queryscope ${chalk.cyan("start")}   Start the stack (requires a previous init)
  queryscope ${chalk.cyan("reset")}   Delete all benchmark runs and metrics
`;

switch (command) {
  case "init":
    await cmdInit();
    break;
  case "start":
    await cmdStart();
    break;
  case "reset":
    await cmdReset();
    break;
  default:
    console.log(HELP);
    if (command && command !== "--help" && command !== "-h") {
      fatal(`Unknown command: ${command}`);
    }
}
