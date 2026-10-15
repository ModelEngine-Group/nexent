import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "../../../frontend/node_modules/@playwright/test/index.mjs";

const stageRoot = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  testDir: stageRoot,
  testMatch: "agent-config-layout.spec.mjs",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1,
  outputDir: path.resolve(
    stageRoot,
    "../../artifacts/agent-config-empty-layout",
  ),
  use: {
    headless: true,
    actionTimeout: 15000,
    navigationTimeout: 30000,
    viewport: { width: 1920, height: 1080 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
