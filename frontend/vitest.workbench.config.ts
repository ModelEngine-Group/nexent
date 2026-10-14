import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  // Required for rolldown/oxc to parse JSX in .tsx test files (same as the
  // root vitest.config.ts; without it every .tsx suite fails to transform).
  oxc: {
    jsx: { runtime: "automatic" },
  },
  resolve: {
    alias: [
      {
        find: /^@\/app\//,
        replacement: fileURLToPath(new URL("./app/[locale]/", import.meta.url)),
      },
      { find: "@", replacement: fileURLToPath(new URL("./", import.meta.url)) },
    ],
  },
  test: {
    environment: "jsdom",
    include: ["tests/workbench/**/*.test.{ts,tsx}"],
    setupFiles: ["./tests/workbench/setup.ts"],
    restoreMocks: true,
    testTimeout: 10_000,
  },
});
