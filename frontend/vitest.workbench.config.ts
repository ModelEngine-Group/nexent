// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  oxc: { jsx: { runtime: "automatic" } },
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
