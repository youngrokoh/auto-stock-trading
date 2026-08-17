import { defineConfig } from "@playwright/test";

export default defineConfig({
  expect: { timeout: 5_000 },
  fullyParallel: true,
  outputDir: "test-results",
  projects: [
    { name: "mobile", use: { viewport: { height: 844, width: 390 } } },
    { name: "tablet", use: { viewport: { height: 1024, width: 768 } } },
    { name: "desktop", use: { viewport: { height: 908, width: 1360 } } },
  ],
  reporter: [["list"], ["html", { open: "never" }]],
  testDir: "./tests/e2e",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5173",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
