// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
import { selectWorkbenchModel } from "@/features/model-controls/modelOptions";

it("switches models without leaking sampling overrides and retains output settings", () => {
  const config = {
    ...initialWorkbenchState.config,
    model_id: 11,
    generation_config: {
      deep_thinking: true,
      thinking_effort: "xhigh" as const,
      temperature: 0.43,
      top_p: 0.78,
      requested_output_tokens: 2048,
    },
  };
  const model: ModelOption = {
    ...reasoningModelFixture,
    id: 12,
    name: "B",
    enableThinking: false,
    reasoningCapability: {
      status: "supported",
      control: "effort",
      levels: ["low", "xhigh"],
      source: "catalog",
    },
  };
  const next = selectWorkbenchModel(config, [model], 12);
  expect(next.generation_config).toMatchObject({
    deep_thinking: false,
    temperature: undefined,
    top_p: undefined,
    requested_output_tokens: 2048,
  });
  expect(next.generation_config.thinking_effort).toBe("auto");
  expect(config.model_id).toBe(11);
  expect(
    selectWorkbenchModel(next, [model], 11, config.generation_config)
      .generation_config
  ).toMatchObject({ temperature: 0.43, top_p: 0.78 });
});

const reasoningAgentFixture: Agent = {
  id: "7",
  name: "Reasoning Agent",
  description: "Fixture",
  model: "qwen",
  max_step: 5,
  provide_run_summary: false,
  tools: [],
};
const reasoningModelFixture: ModelOption = {
  id: 11,
  name: "qwen",
  displayName: "Reasoning Model",
  type: "llm",
  source: "openai",
  apiKey: "",
  apiUrl: "https://example.invalid",
  maxTokens: 0,
  connect_status: "available",
};
it.each([false, true, undefined])(
  "capability levels are identical in both scopes with saved thinking=%s",
  (enableThinking) => {
    const capability = {
      status: "supported" as const,
      control: "effort" as const,
      levels: ["low", "medium", "xhigh"] as const,
      source: "catalog" as const,
    };
    const catalog: ModelOption[] = [
      {
        ...reasoningModelFixture,
        id: 11,
        name: "qwen",
        type: "llm",
        connect_status: "available",
        enableThinking,
        reasoningCapability: { ...capability, levels: [...capability.levels] },
      },
    ];
    const agent: Agent = {
      ...reasoningAgentFixture,
      id: "7",
      model_ids: [11],
      model_names: ["qwen"],
      model_params_override: {
        "11": { extra_params: { enable_thinking: enableThinking } },
      },
    };
    const tenant = deriveModelOptions(agent, catalog, "tenant")[0];
    const configured = deriveModelOptions(agent, catalog, "agent")[0];
    expect(configured.efforts).toEqual(tenant.efforts);
    expect(configured.efforts).toEqual(
      ["auto", "low", "medium", "xhigh"].map((id) => ({ id, name: id }))
    );
  }
);

it("resolves stale defaults while retaining valid overrides and other Workbench parameters", () => {
  const model: ModelOption = {
    ...reasoningModelFixture,
    id: 11,
    name: "qwen",
    type: "llm",
    connect_status: "available",
    reasoningCapability: {
      status: "supported",
      control: "effort",
      levels: ["low", "xhigh"],
      source: "catalog",
    },
  };
  const config = {
    ...initialWorkbenchState.config,
    model_id: 11,
    generation_config: {
      deep_thinking: true,
      thinking_effort: "high" as const,
      temperature: 0.7,
      top_p: 0.81,
      requested_output_tokens: 2000,
    },
  };
  expect(withDefaultWorkbenchModel(config, [model]).generation_config).toEqual({
    ...config.generation_config,
    thinking_effort: "auto",
  });
  const valid = {
    ...config,
    generation_config: {
      ...config.generation_config,
      thinking_effort: "xhigh" as const,
    },
  };
  expect(withDefaultWorkbenchModel(valid, [model])).toBe(valid);
  const agent: Agent = {
    ...reasoningAgentFixture,
    id: "7",
    model_ids: [11],
    model_names: ["qwen"],
    model_params_override: {
      "11": {
        extra_params: { enable_thinking: false, reasoning_effort: "high" },
      },
    },
  };
  expect(deriveModelOptions(agent, [model])[0].defaultEffort).toBe("auto");
  agent.model_params_override = {
    "11": {
      extra_params: { enable_thinking: false, reasoning_effort: "xhigh" },
    },
  };
  expect(deriveModelOptions(agent, [model])[0].defaultEffort).toBe("xhigh");
});

it.each(["unsupported", "unknown"] as const)(
  "does not invent effort levels for %s capability",
  (status) => {
    const model: ModelOption = {
      ...reasoningModelFixture,
      id: 11,
      name: "plain",
      type: "llm",
      connect_status: "available",
      reasoningCapability: {
        status,
        control: "effort",
        levels: [],
        source: "catalog",
      },
    };
    const agent: Agent = {
      ...reasoningAgentFixture,
      id: "7",
      model_ids: [11],
      model_names: ["plain"],
    };
    for (const scope of ["agent", "tenant"] as const) {
      expect(
        deriveModelOptions(agent, [model], scope)[0].efforts
      ).toBeUndefined();
    }
  }
);

it("keeps budget controls available with saved thinking disabled without converting them to effort", () => {
  const model: ModelOption = {
    ...reasoningModelFixture,
    id: 11,
    name: "budget",
    type: "llm",
    connect_status: "available",
    reasoningCapability: {
      status: "supported",
      control: "budget_tokens",
      levels: [],
      source: "catalog",
      controls: [{ type: "budget_tokens", min: 1024, max: 8192 }],
    },
  };
  const agent: Agent = {
    ...reasoningAgentFixture,
    id: "7",
    model_ids: [11],
    model_names: ["budget"],
    model_params_override: {
      "11": {
        extra_params: { enable_thinking: false, reasoning_budget_tokens: 2048 },
      },
    },
  };
  expect(deriveModelOptions(agent, [model])[0]).toMatchObject({
    budgetTokens: { min: 1024, max: 8192 },
    defaultBudgetTokens: 2048,
  });
  expect(deriveModelOptions(agent, [model])[0].efforts).toBeUndefined();
});

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
  expect(withDefaultWorkbenchModel(explicit, available).model_id).toBe(12);
  expect(withDefaultWorkbenchModel(initialWorkbenchState.config, [])).toBe(
    initialWorkbenchState.config
  );
});
it("prefers the tenant default LLM as the Workbench fallback model", () => {
  const available = [{ id: 11 }, { id: 12 }, { id: 13 }];
  // A configured, selectable tenant default wins over the first catalog entry.
  expect(
    withDefaultWorkbenchModel(initialWorkbenchState.config, available, 13)
      .model_id
  ).toBe(13);
  // A tenant default that is missing or unavailable falls back to the first.
  expect(
    withDefaultWorkbenchModel(initialWorkbenchState.config, available, 99)
      .model_id
  ).toBe(11);
  // Unset (undefined) and zero ("not configured") ids also fall back.
  expect(
    withDefaultWorkbenchModel(initialWorkbenchState.config, available).model_id
  ).toBe(11);
  expect(
    withDefaultWorkbenchModel(initialWorkbenchState.config, available, 0)
      .model_id
  ).toBe(11);
  // An explicit session choice still wins over the tenant default.
  const explicit = { ...initialWorkbenchState.config, model_id: 12 };
  expect(withDefaultWorkbenchModel(explicit, available, 13).model_id).toBe(12);
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
    {
      id: "11",
      name: "Model A",
      reasoningCapability: undefined,
      defaultDeepThinking: false,
    },
    {
      id: "12",
      name: "Model B",
      reasoningCapability: undefined,
      defaultDeepThinking: false,
    },
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
    {
      id: "11",
      name: "Configured Model",
      reasoningCapability: undefined,
      defaultDeepThinking: false,
    },
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
  const catalog = [
    {
      id: 11,
      name: "reasoning-model",
      displayName: "Reasoning model",
      type: "llm",
      connect_status: "available",
      enableThinking: true,
      reasoningCapability: capability,
    },
  ] as ModelOption[];
  const agent = {
    id: "7",
    model_ids: [11],
    model_names: ["Reasoning model"],
  } as Agent;

  expect(deriveModelOptions(agent, catalog, "agent")[0]).toMatchObject({
    reasoningCapability: capability,
    efforts: [{ id: "auto" }, { id: "low" }, { id: "high" }],
    defaultEffort: "auto",
  });
  expect(deriveModelOptions(agent, catalog, "tenant")[0]).toMatchObject({
    reasoningCapability: capability,
  });
});

it("keeps an explicitly configured model reasoning default", () => {
  const catalog = [
    {
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
    },
  ] as ModelOption[];
  const agent = {
    id: "7",
    model_ids: [11],
    model_names: ["Reasoning model"],
  } as Agent;

  expect(deriveModelOptions(agent, catalog, "agent")[0].defaultEffort).toBe(
    "high"
  );
});

it("defaults an enabled Agent reasoning override without a configured effort to auto", () => {
  const catalog = [
    {
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
    },
  ] as ModelOption[];
  const agent: Agent = {
    id: "7",
    name: "reasoning-agent",
    description: "Agent used to verify reasoning defaults",
    model: "reasoning-model",
    max_step: 5,
    provide_run_summary: false,
    tools: [],
    model_ids: [11],
    model_names: ["Reasoning model"],
    model_params_override: {
      "11": { extra_params: { enable_thinking: true } },
    },
  };

  expect(deriveModelOptions(agent, catalog, "agent")[0].defaultEffort).toBe(
    "auto"
  );
});

it("inherits model effort when Agent only overrides the toggle, and prefers an explicit Agent effort", () => {
  const model: ModelOption = {
    ...reasoningModelFixture,
    enableThinking: true,
    defaultReasoningEffort: "medium",
    reasoningCapability: {
      status: "supported",
      control: "effort",
      source: "catalog",
      levels: ["low", "medium", "xhigh"],
    },
  };
  const agent: Agent = {
    ...reasoningAgentFixture,
    model_ids: [11],
    model_names: ["qwen"],
    model_params_override: {
      "11": { extra_params: { enable_thinking: false } },
    },
  };
  expect(deriveModelOptions(agent, [model])[0]).toMatchObject({
    defaultDeepThinking: false,
    defaultEffort: "medium",
  });
  agent.model_params_override!["11"].extra_params!.reasoning_effort = "xhigh";
  expect(deriveModelOptions(agent, [model])[0].defaultEffort).toBe("xhigh");
  expect(deriveModelOptions(agent, [model], "tenant")[0].defaultEffort).toBe(
    "medium"
  );
  expect(
    withDefaultWorkbenchModel(initialWorkbenchState.config, [model])
      .generation_config
  ).toMatchObject({ deep_thinking: true, thinking_effort: "medium" });
});

it("preserves automatic defaults when no persisted model effort exists", () => {
  const model: ModelOption = {
    ...reasoningModelFixture,
    enableThinking: true,
    reasoningCapability: {
      status: "supported",
      control: "effort",
      source: "catalog",
      levels: ["low", "medium"],
      default: "medium",
    },
  };
  expect(
    deriveModelOptions(reasoningAgentFixture, [model], "tenant")[0]
      .defaultEffort
  ).toBe("auto");
  expect(
    withDefaultWorkbenchModel(initialWorkbenchState.config, [model])
      .generation_config.thinking_effort
  ).toBe("auto");
  expect(
    selectWorkbenchModel(
      { ...initialWorkbenchState.config, model_id: 12 },
      [model],
      11
    ).generation_config.thinking_effort
  ).toBe("auto");
});

it("keeps unconfigured reasoning automatic instead of substituting a capability default", () => {
  const model: ModelOption = {
    ...reasoningModelFixture,
    enableThinking: false,
    reasoningCapability: {
      status: "supported",
      control: "effort",
      source: "catalog",
      default: "high",
      levels: ["low", "high", "xhigh"],
    },
  };
  const agent: Agent = {
    ...reasoningAgentFixture,
    model_ids: [11],
    model_names: ["qwen"],
    model_params_override: {
      "11": { extra_params: { enable_thinking: true } },
    },
  };
  for (const scope of ["agent", "tenant"] as const) {
    expect(deriveModelOptions(agent, [model], scope)[0].defaultEffort).toBe(
      "auto"
    );
  }
  const config = {
    ...initialWorkbenchState.config,
    model_id: 11,
    generation_config: {
      deep_thinking: false,
      thinking_effort: "xhigh" as const,
      temperature: 0.43,
      top_p: 0.78,
      requested_output_tokens: 2048,
    },
  };
  expect(
    selectWorkbenchModel(config, [model], 11).generation_config
  ).toMatchObject({
    thinking_effort: "auto",
    temperature: 0.43,
    top_p: 0.78,
    requested_output_tokens: 2048,
  });
  expect(
    withDefaultWorkbenchModel(initialWorkbenchState.config, [model])
      .generation_config.thinking_effort
  ).toBe("auto");
  expect(
    deriveModelOptions(
      agent,
      [{ ...model, defaultReasoningEffort: "low" }],
      "agent"
    )[0].defaultEffort
  ).toBe("low");
  agent.model_params_override!["11"].extra_params!.reasoning_effort = "xhigh";
  expect(
    deriveModelOptions(
      agent,
      [{ ...model, defaultReasoningEffort: "low" }],
      "agent"
    )[0].defaultEffort
  ).toBe("xhigh");
});

it("displays per-field Agent and model sampling defaults without leaking them into tenant scope", () => {
  const model: ModelOption = {
    ...reasoningModelFixture,
    temperature: 0.45,
    topP: 0.83,
  };
  const agent: Agent = {
    ...reasoningAgentFixture,
    model_ids: [11],
    model_names: ["qwen"],
    model_params_override: { "11": { temperature: 0, top_p: null } },
  };
  expect(
    deriveModelOptions(agent, [model], "agent")[0].defaultSampling
  ).toEqual({ temperature: 0, top_p: 0.83 });
  expect(
    deriveModelOptions(agent, [model], "tenant")[0].defaultSampling
  ).toEqual({ temperature: 0.45, top_p: 0.83 });
  expect(
    deriveModelOptions(agent, [reasoningModelFixture], "tenant")[0]
      .defaultSampling
  ).toBeUndefined();
  expect(agent.model_params_override).toEqual({
    "11": { temperature: 0, top_p: null },
  });
});

it("uses backend SDK sampling metadata only as the final per-field display fallback", () => {
  const model: ModelOption = {
    ...reasoningModelFixture,
    effectiveSampling: { temperature: 1, top_p: 1 },
  };
  const agent: Agent = {
    ...reasoningAgentFixture,
    model_ids: [11],
    model_names: ["qwen"],
    model_params_override: { "11": { temperature: 0, top_p: null } },
  };
  expect(
    deriveModelOptions(agent, [model], "agent")[0].defaultSampling
  ).toEqual({ temperature: 0, top_p: 1 });
  expect(
    deriveModelOptions(agent, [model], "tenant")[0].defaultSampling
  ).toEqual({ temperature: 1, top_p: 1 });
  expect(
    deriveModelOptions(agent, [{ ...model, topP: 0.87 }], "agent")[0]
      .defaultSampling
  ).toEqual({ temperature: 0, top_p: 0.87 });
  expect(model.temperature).toBeUndefined();
  expect(model.topP).toBeUndefined();
});
