import { expect, it } from "vitest";
import {
  initialWorkbenchState,
  workbenchReducer,
} from "@/features/workbench/state";
import {
  deriveModelOptions,
  withDefaultWorkbenchModel,
} from "@/features/workbench/modelOptions";
import type { Agent } from "@/types/agentConfig";
import type { ModelOption } from "@/types/modelConfig";

const preview = {
  agent_id: 1,
  version_no: 2,
  default_skill_mounts: [],
  knowledge: {},
};

it("uses the first available tenant model as Workbench default without replacing an explicit choice", () => {
  expect(initialWorkbenchState.config.generation_config.thinking_effort).toBe(
    "low"
  );
  const available = [{ id: 11 }, { id: 12 }];
  expect(
    withDefaultWorkbenchModel(initialWorkbenchState.config, available).model_id
  ).toBe(11);
  const explicit = { ...initialWorkbenchState.config, model_id: 12 };
  expect(withDefaultWorkbenchModel(explicit, available)).toBe(explicit);
  expect(withDefaultWorkbenchModel(initialWorkbenchState.config, [])).toBe(
    initialWorkbenchState.config
  );
});
it("does not replace the Workbench model with the mounted Agent model", () => {
  const next = workbenchReducer(initialWorkbenchState, {
    type: "resolve-agent-success",
    preview,
    modelIds: [8, 9],
  });
  expect(next.config.model_id).toBeUndefined();
});
it("preserves a tenant model across changes to mounted Agents", () => {
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
  ).toBe(9);
  expect(
    workbenchReducer(state, {
      type: "resolve-agent-success",
      preview,
      modelIds: [],
    }).config.model_id
  ).toBe(9);
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
    { id: "11", name: "Model A", efforts: true, defaultEffort: "low" },
    { id: "12", name: "Model B", efforts: true, defaultEffort: "low" },
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

it("preserves catalog reasoning capabilities for the shared model selector", () => {
  const capability = {
    status: "supported" as const,
    control: "effort" as const,
    levels: ["low" as const, "high" as const],
    controls: [{ type: "effort" as const, values: ["low", "high"] }],
    source: "catalog" as const,
  };
  const catalog = [{
    id: 11,
    name: "reasoning-model",
    displayName: "Reasoning model",
    type: "llm",
    connect_status: "available",
    enableThinking: true,
    reasoningCapability: capability,
  }] as ModelOption[];
  const agent = { id: "7", model_ids: [11], model_names: ["Reasoning model"] } as Agent;

  expect(deriveModelOptions(agent, catalog, "agent")[0]).toMatchObject({
    reasoningCapability: capability,
    efforts: [{ id: "auto" }, { id: "low" }, { id: "high" }],
    defaultEffort: "low",
  });
  expect(deriveModelOptions(agent, catalog, "tenant")[0]).toMatchObject({
    reasoningCapability: capability,
  });
});

it("keeps an explicitly configured model reasoning default", () => {
  const catalog = [{
    id: 11,
    name: "reasoning-model",
    displayName: "Reasoning model",
    type: "llm",
    connect_status: "available",
    enableThinking: true,
    defaultReasoningEffort: "high",
    reasoningCapability: {
      status: "supported",
      control: "effort",
      levels: ["low", "high"],
      controls: [{ type: "effort", values: ["low", "high"] }],
      source: "catalog",
    },
  }] as ModelOption[];
  const agent = { id: "7", model_ids: [11], model_names: ["Reasoning model"] } as Agent;

  expect(deriveModelOptions(agent, catalog, "agent")[0].defaultEffort).toBe("high");
});

it("defaults an enabled Agent reasoning override without an effort to low", () => {
  const catalog = [{
    id: 11,
    name: "reasoning-model",
    displayName: "Reasoning model",
    type: "llm",
    connect_status: "available",
    enableThinking: true,
    reasoningCapability: {
      status: "supported",
      control: "effort",
      levels: ["low", "high"],
      controls: [{ type: "effort", values: ["low", "high"] }],
      source: "catalog",
    },
  }] as ModelOption[];
  const agent = {
    id: "7",
    model_ids: [11],
    model_names: ["Reasoning model"],
    model_params_override: {
      "11": { extra_params: { enable_thinking: true } },
    },
  } as Agent;

  expect(deriveModelOptions(agent, catalog, "agent")[0].defaultEffort).toBe("low");
});
