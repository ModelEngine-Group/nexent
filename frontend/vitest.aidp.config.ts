import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const require = createRequire(import.meta.url);

export default defineConfig({
  root: path.resolve(frontendRoot, ".."),
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: [
      {
        find: "@/app/i18n",
        replacement: path.join(frontendRoot, "tests/component/i18nStub.ts"),
      },
      { find: "@", replacement: frontendRoot },
      // Resolve formal component-test dependencies from the frontend installation.
      ...[
        "react",
        "react-dom",
        "react/jsx-runtime",
        "react/jsx-dev-runtime",
        "react-i18next",
        "antd",
        "vitest",
        "@testing-library/react",
        "@testing-library/user-event",
      ].map((name) => ({
        find: new RegExp(`^${name}$`),
        replacement:
          name === "vitest"
            ? path.join(
                path.dirname(require.resolve("vitest/package.json")),
                "dist/index.js"
              )
            : require.resolve(name),
      })),
    ],
  },
  test: {
    environment: "jsdom",
    setupFiles: [path.join(frontendRoot, "tests/component/setup.ts")],
    include: [
      "test/automation/d1/AidpImportDrawer.test.tsx",
      "test/automation/d1/AidpUploadService.test.tsx",
      "test/automation/d1/AidpGroupNamesDisplay.test.tsx",
    ],
    clearMocks: true,
  },
});
