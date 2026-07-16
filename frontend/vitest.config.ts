import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname) },
  },
  test: {
    environment: "jsdom",
    include: ["components/nl2agent/__tests__/*.{test,vitest.test}.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
  },
});
