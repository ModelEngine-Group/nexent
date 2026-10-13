import { defineConfig } from "playwright/test";
import { join } from "node:path";

const fakeAudio = process.env.NEXENT_TEST_BROWSER_FAKE_AUDIO;

export default defineConfig({
  testDir: "../../../cases",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: Number(process.env.D4_WORKERS || "1"),
  retries: 0,
  timeout: Number(process.env.D4_CASE_TIMEOUT_MS || "1800000"),
  expect: { timeout: Number(process.env.D4_ASSERT_TIMEOUT_MS || "30000") },
  reporter: [["line"]],
  outputDir: process.env.D4_PLAYWRIGHT_OUTPUT_DIR || join(process.env.RESULT_DIR || ".", ".playwright-internal"),
  use: {
    baseURL: process.env.NEXENT_BASE_URL || "http://localhost:3000",
    locale: "zh-CN",
    actionTimeout: Number(process.env.D4_ACTION_TIMEOUT_MS || "30000"),
    navigationTimeout: Number(process.env.D4_NAVIGATION_TIMEOUT_MS || "60000"),
    screenshot: "off",
    trace: "off",
    video: "off",
    headless: true,
    permissions: ["microphone"],
    launchOptions: {
      args: fakeAudio
        ? ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", `--use-file-for-fake-audio-capture=${fakeAudio}`]
        : [],
    },
  },
});
