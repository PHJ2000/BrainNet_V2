import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: { baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:18080", browserName: "chromium", viewport: { width: 1440, height: 1000 } },
});
