import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:18082",
    headless: true,
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {},
  },
  webServer: [
    {
      command: "node e2e/mock-upstream.mjs",
      url: "http://127.0.0.1:19090/health",
      reuseExistingServer: false,
    },
    {
      command: "HOST=127.0.0.1 PORT=18082 DOTTY_BEHAVIOUR_URL=http://127.0.0.1:19090 DOTTY_BRIDGE_URL=http://127.0.0.1:19090 XIAOZHI_HTTP_URL=http://127.0.0.1:19090 DOTTY_PI_URL=http://127.0.0.1:19090 node dist-server/index.js",
      url: "http://127.0.0.1:18082/health",
      reuseExistingServer: false,
    },
  ],
});
