import { defineConfig, devices } from "@playwright/test";

// Nothing listens here - test 3 needs the backend genuinely unreachable, not
// just misconfigured. NEXT_PUBLIC_AGENT_API_URL is inlined at build time, so
// this has to come from the webServer's build+start command, not a runtime
// override.
const DEAD_BACKEND_URL = "http://127.0.0.1:19999";
const PORT = 3100;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "on-first-retry",
  },
  webServer: {
    // One production build+server for all 3 tests. The dead backend URL is
    // harmless for tests 1-2 (neither depends on backend connectivity) and
    // is exactly what test 3 needs.
    command: `npm run build && npm run start -- -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      NEXT_PUBLIC_AGENT_API_URL: DEAD_BACKEND_URL,
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
