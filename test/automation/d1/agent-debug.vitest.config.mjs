import { mergeConfig } from "../../../frontend/node_modules/vitest/dist/config.js";
import base from "./agent-config.vitest.config.mjs";
export default mergeConfig(base, {
  test: { include: ["../test/automation/d1/agent-debug-layout.test.tsx"] },
});
