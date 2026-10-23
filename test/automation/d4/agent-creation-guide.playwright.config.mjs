import base from "./agent-config.playwright.config.mjs";
export default {
  ...base,
  testMatch: "agent-creation-guide.spec.mjs",
  outputDir: "../../artifacts/agent-creation-guide",
};
