import base from "./agent-config.vitest.config.mjs";
export default {
  ...base,
  test: {
    ...base.test,
    include: ["../test/automation/d1/agent-creation-guide.test.tsx"],
  },
};
