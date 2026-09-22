// ARG-073…080 · the end-to-end script runs against the built console, served with the API of
// `e2e/server.mjs` on one origin, as the appliance serves it. Browsers are never downloaded on the
// fly: `make console-e2e-setup` does it, out loud.
import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;
const BASE = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: BASE, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npm run build -- --mode e2e && node e2e/server.mjs`,
    url: BASE,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
