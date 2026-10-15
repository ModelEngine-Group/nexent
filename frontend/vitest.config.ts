import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  oxc: {
    jsx: { runtime: "automatic" },
  },
  resolve: {
    alias: [
      {
        find: "@/app/i18n",
        replacement: path.resolve(__dirname, "tests/component/i18nStub.ts"),
      },
      { find: "@", replacement: path.resolve(__dirname) },
    ],
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/component/setup.ts"],
    include: ["tests/component/**/*.test.tsx"],
    clearMocks: true,
    // Component specs render the whole antd agent workspace and mirror the D1
    // harness (test/automation/d1/agent-config.vitest.config.mjs), which also
    // allows 30s per test; the 5s default is too tight for a full page render.
    testTimeout: 30_000,
  },
});
