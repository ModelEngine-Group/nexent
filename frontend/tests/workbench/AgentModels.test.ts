import { expect, it } from "vitest";
import {
  initialWorkbenchState,
  workbenchReducer,
} from "@/features/workbench/state";

const preview = {
  agent_id: 1,
  version_no: 2,
  default_skill_mounts: [],
  knowledge: {},
};
it("injects the first configured model when selecting a single agent", () => {
  const next = workbenchReducer(initialWorkbenchState, {
    type: "resolve-agent-success",
    preview,
    modelIds: [8, 9],
  });
  expect(next.config.model_id).toBe(8);
});
it("preserves a valid choice and replaces a model outside the new agent list", () => {
  const state = {
    ...initialWorkbenchState,
    config: { ...initialWorkbenchState.config, model_id: 9 },
  };
  expect(
    workbenchReducer(state, {
      type: "resolve-agent-success",
      preview,
      modelIds: [8, 9],
    }).config.model_id
  ).toBe(9);
  expect(
    workbenchReducer(state, {
      type: "resolve-agent-success",
      preview,
      modelIds: [3],
    }).config.model_id
  ).toBe(3);
  expect(
    workbenchReducer(state, {
      type: "resolve-agent-success",
      preview,
      modelIds: [],
    }).config.model_id
  ).toBeUndefined();
});
