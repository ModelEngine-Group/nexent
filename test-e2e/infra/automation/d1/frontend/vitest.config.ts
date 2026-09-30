import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";

const repo = process.env.NEXENT_REPO;
if (!repo) throw new Error("NEXENT_REPO is required; set it in config/daily.env");
const frontend = path.join(repo, "frontend");
const productModules = process.env.NEXENT_TEST_FRONTEND_MODULES || path.join(frontend, "node_modules");
const testNodeModules = path.resolve(__dirname, "node_modules");

export default defineConfig({
  server: {
    fs: {
      allow: [path.resolve(__dirname), repo],
    },
    deps: {
      // These packages import CSS or assistant-ui state through ESM. Keep
      // them in Vite's transform pipeline so CSS handling and vi.mock work.
      inline: ["react-shiki", /^@assistant-ui\//],
    },
  },
  plugins: [
    react(),
    tsconfigPaths({ projects: [path.join(frontend, "tsconfig.json")] }),
  ],
  resolve: {
    // Product sources live outside this test package. Force every imported
    // component and dependency to use the test runner's React instance;
    // otherwise hooks fail because two React copies are loaded.
    dedupe: ["react", "react-dom", "react-i18next"],
    alias: [
      // Case files live outside this package; resolve their test-only imports
      // from the isolated runner, not a developer's root node_modules tree.
      { find: /^@testing-library\/(.*)$/, replacement: path.join(testNodeModules, "@testing-library/$1") },
      { find: /^react$/, replacement: path.join(testNodeModules, "react/index.js") },
      { find: /^react\/jsx-runtime$/, replacement: path.join(testNodeModules, "react/jsx-runtime.js") },
      { find: /^react\/jsx-dev-runtime$/, replacement: path.join(testNodeModules, "react/jsx-dev-runtime.js") },
      { find: /^react-dom$/, replacement: path.join(testNodeModules, "react-dom/index.js") },
      { find: /^react-dom\/(.*)$/, replacement: path.join(testNodeModules, "react-dom/$1") },
      { find: /^react-i18next$/, replacement: path.join(testNodeModules, "react-i18next/dist/es/index.js") },
      { find: /^i18next$/, replacement: path.join(testNodeModules, "i18next/dist/esm/i18next.js") },
      { find: /^antd$/, replacement: path.join(testNodeModules, "antd") },
      { find: /^@ant-design\/icons$/, replacement: path.join(testNodeModules, "@ant-design/icons") },
      { find: /^@tanstack\/react-query$/, replacement: path.join(testNodeModules, "@tanstack/react-query") },
      { find: /^react-markdown$/, replacement: path.join(testNodeModules, "react-markdown") },
      { find: /^@dnd-kit\/core$/, replacement: path.join(testNodeModules, "@dnd-kit/core") },
      { find: /^@dnd-kit\/sortable$/, replacement: path.join(testNodeModules, "@dnd-kit/sortable") },
      { find: /^@dnd-kit\/utilities$/, replacement: path.join(testNodeModules, "@dnd-kit/utilities") },
      { find: /^react-shiki$/, replacement: path.join(testNodeModules, "react-shiki") },
      { find: /^@assistant-ui\/react$/, replacement: path.join(testNodeModules, "@assistant-ui/react") },
      { find: /^@assistant-ui\/react-markdown$/, replacement: path.join(testNodeModules, "@assistant-ui/react-markdown") },
      // Next is a product runtime dependency. Resolve its subpath exports from
      // the checked-out product tree rather than installing a second copy.
      { find: /^next\/(.*)$/, replacement: path.join(productModules, "next/$1") },
      // Nexent tsconfig: @/app/* -> ./app/[locale]/*
      // Only match @/app/ paths that don't already contain [locale]
      { find: /^@\/app\/(?!\[locale\])(.*)$/, replacement: path.join(frontend, "app/[locale]/$1") },
      // Default: @ -> frontend root
      { find: "@", replacement: frontend },
    ],
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: [path.resolve(__dirname, "setup.ts")],
    include: [path.resolve(__dirname, "../../../../cases/**/*.test.{ts,tsx}").split(path.sep).join("/")],
    clearMocks: true,
    // Generated suites install module-level mock implementations. Restoring
    // them before each test erases mockResolvedValue/mockImplementation and
    // turns valid service stubs into undefined-returning functions.
    restoreMocks: false,
  },
});
