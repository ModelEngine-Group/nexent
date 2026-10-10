import { defineConfig } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import base from "./agent-config.playwright.config.mjs";
export default defineConfig({
  ...base,
  testMatch: "agent-debug-layout.spec.mjs",
  outputDir: "../../artifacts/agent-debug-layout",
});
