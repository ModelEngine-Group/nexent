import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { defineConfig } from "../../../frontend/node_modules/vitest/dist/config.js";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../",
);
const frontendRoot = path.join(repositoryRoot, "frontend");
const frontendRequire = createRequire(path.join(frontendRoot, "package.json"));

export default defineConfig({
  root: frontendRoot,
  resolve: {
    alias: [
      {
        find: "@/app/i18n",
        replacement: path.join(frontendRoot, "tests/component/i18nStub.ts"),
      },
      { find: "@/app", replacement: path.join(frontendRoot, "app/[locale]") },
      { find: "@", replacement: frontendRoot },
      {
        find: /^vitest$/,
        replacement: path.join(
          frontendRoot,
          "node_modules/vitest/dist/index.js",
        ),
      },
      ...[
        "react",
        "react/jsx-runtime",
        "react/jsx-dev-runtime",
        "react-dom",
        "react-dom/client",
        "@testing-library/react",
        "antd",
        "react-i18next",
        "@tanstack/react-query",
        "next/navigation",
      ].map((name) => ({
        find: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`),
        replacement: frontendRequire.resolve(name),
      })),
    ],
  },
  test: {
    environment: "jsdom",
    setupFiles: [path.join(frontendRoot, "tests/component/setup.ts")],
    include: ["../test/automation/d1/agent-config-*.test.tsx"],
    clearMocks: true,
    testTimeout: 30000,
  },
});
