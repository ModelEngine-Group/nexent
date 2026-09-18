import { expect, it } from "vitest";
import {
  initialWorkbenchState,
  workbenchReducer,
} from "@/features/workbench/state";
import { deriveModelOptions } from "@/features/workbench/modelOptions";
import type { Agent } from "@/types/agentConfig";
import type { ModelOption } from "@/types/modelConfig";

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

it("lists every available tenant LLM for the generic workbench agent", () => {
  const agent = { id: "__workbench_empty__" } as Agent;
  const catalog = [
    {
      id: 11,
      name: "model-a",
      displayName: "Model A",
      type: "llm",
      connect_status: "available",
    },
    {
      id: 12,
      name: "model-b",
      displayName: "Model B",
      type: "llm",
      connect_status: "available",
    },
    {
      id: 13,
      name: "offline",
      displayName: "Offline",
      type: "llm",
      connect_status: "unavailable",
    },
    {
      id: 14,
      name: "embedding",
      displayName: "Embedding",
      type: "embedding",
      connect_status: "available",
    },
  ] as ModelOption[];

  expect(deriveModelOptions(agent, catalog, "tenant")).toEqual([
    { id: "11", name: "Model A" },
    { id: "12", name: "Model B" },
  ]);
});

it("keeps single-agent model selection restricted to configured models", () => {
  const agent = {
    id: "7",
    model_ids: [11],
    model_names: ["Configured Model"],
  } as Agent;
  const catalog = [
    {
      id: 11,
      name: "configured",
      displayName: "Configured Model",
      type: "llm",
      connect_status: "available",
    },
    {
      id: 12,
      name: "other",
      displayName: "Other Model",
      type: "llm",
      connect_status: "available",
    },
  ] as ModelOption[];

  expect(deriveModelOptions(agent, catalog, "agent")).toEqual([
    { id: "11", name: "Configured Model" },
  ]);
});
