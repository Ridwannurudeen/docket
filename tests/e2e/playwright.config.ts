import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/* One uvicorn against a throwaway database, started by Playwright and torn down with it.
   The database is a fresh temporary file every run: these tests must never be able to read
   or write a developer's real snapshot, and a suite that shares state with the checkout is
   a suite whose results depend on what was run before it. */

/* Playwright transpiles this file to CommonJS unless the package declares ES modules, so
   the directory comes from `__dirname` rather than from `import.meta`. */
const REPO = join(__dirname, "..", "..");

/* The interpreter the repository's own instructions create. `DOCKET_PYTHON` overrides it
   for CI, where the venv lives wherever the workflow put it. */
const PYTHON =
  process.env.DOCKET_PYTHON ??
  (process.platform === "win32"
    ? join(REPO, ".venv", "Scripts", "python.exe")
    : join(REPO, ".venv", "bin", "python"));

const PORT = Number(process.env.DOCKET_E2E_PORT ?? 8931);
const BASE_URL = `http://127.0.0.1:${PORT}`;
const DB = join(mkdtempSync(join(tmpdir(), "docket-e2e-")), "e2e.sqlite3");

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  /* One worker: the pages under test are stateless shells, but the server behind them
     holds one free-tier allowance window per client address, and parallel workers would
     race each other through it. */
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  /* The mobile spec sets its own viewport with `test.use`, so it runs once under its own
     project and is kept out of the desktop one rather than running twice at one width. */
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"] },
      testIgnore: /mobile\.spec\.ts/,
    },
    {
      name: "mobile",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /mobile\.spec\.ts/,
    },
  ],
  webServer: {
    command: `"${PYTHON}" -m uvicorn docket.api:create_app --factory --host 127.0.0.1 --port ${PORT}`,
    cwd: REPO,
    url: `${BASE_URL}/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "pipe",
    stderr: "pipe",
    env: { DOCKET_DB: DB, PYTHONUNBUFFERED: "1" },
  },
});
