import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: { jsx: "automatic" },
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
  },
});
