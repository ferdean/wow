import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  forbidOnly: true,
  retries: 0,
  use: { baseURL: "https://127.0.0.1:18443", ignoreHTTPSErrors: true },
  projects: [{ name: "webkit", use: { ...devices["iPhone 17"] } }],
  webServer: {
    command: "rm -rf build/e2e-data && uv run --offline wow --config display/e2e/wow.toml --sim",
    cwd: "..",
    url: "https://127.0.0.1:18443/",
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
