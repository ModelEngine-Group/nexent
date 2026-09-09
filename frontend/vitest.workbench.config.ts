import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  resolve: {
    alias: [
      {
        find: /^@\/app\//,
        replacement: fileURLToPath(new URL("./app/[locale]/", import.meta.url)),
      },
      { find: "@", replacement: fileURLToPath(new URL("./", import.meta.url)) },
    ],
  },
  oxc: { jsx: { runtime: "automatic" } },
  test: {
    environment: "jsdom",
    include: ["tests/workbench/**/*.test.{ts,tsx}"],
    setupFiles: ["./tests/workbench/setup.ts"],
    restoreMocks: true,
  },
});
