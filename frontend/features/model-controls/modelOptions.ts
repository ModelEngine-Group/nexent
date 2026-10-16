// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { agentParameterValues } from "@/lib/modelParameterLayers";
import type { Agent, PublishedAgent } from "@/types/agentConfig";
import type {
  ModelOption as CatalogModelOption,
  ReasoningEffort,
} from "@/types/modelConfig";
import type { ModelOption as SelectorModelOption } from "@/app/newchat/ui/model-selector";
import { DEFAULT_REASONING_EFFORT } from "@/const/modelConfig";
import { isReasoningEffort } from "@/lib/modelReasoning";
import type { WorkbenchSessionConfig } from "@/features/workbench/types";

export type ModelSelectionScope = "agent" | "tenant";

function configuredEffort(
  model?: Pick<
    CatalogModelOption,
    "defaultReasoningEffort" | "reasoningCapability"
  >
): ReasoningEffort {
  const value = model?.defaultReasoningEffort;
  return isReasoningEffort(value) ? value : "auto";
}

/** Switch reasoning defaults without changing existing non-reasoning overrides. */
export function selectWorkbenchModel(
  config: WorkbenchSessionConfig,
  models: readonly CatalogModelOption[],
  modelId: number,
  remembered?: Pick<
    WorkbenchSessionConfig["generation_config"],
    "deep_thinking" | "thinking_effort" | "reasoning_budget_tokens"
  >
): WorkbenchSessionConfig {
  const model = models.find((item) => item.id === modelId);
  return withDefaultWorkbenchModel(
    {
      ...config,
      model_id: modelId,
      generation_config: {
        ...config.generation_config,
        deep_thinking: model?.enableThinking ?? false,
        thinking_effort: configuredEffort(model),
        reasoning_budget_tokens:
          typeof model?.extraParams?.reasoning_budget_tokens === "number"
            ? model.extraParams.reasoning_budget_tokens
            : undefined,
        ...remembered,
      },
    },
    models
  );
}

/** Keep the model displayed in Workbench identical to the model sent at run time. */
export function withDefaultWorkbenchModel(
  config: WorkbenchSessionConfig,
  availableLlmModels: readonly Pick<
    CatalogModelOption,
    | "id"
    | "reasoningCapability"
    | "defaultReasoningEffort"
    | "enableThinking"
    | "extraParams"
  >[]
): WorkbenchSessionConfig {
  const modelId = config.model_id ?? availableLlmModels[0]?.id;
  if (modelId == null) return config;
  const model = availableLlmModels.find((item) => item.id === modelId);
  if (!model) return config;
  const generation =
    config.model_id == null
      ? {
          ...config.generation_config,
          deep_thinking: model.enableThinking ?? false,
          thinking_effort: configuredEffort(model),
          reasoning_budget_tokens:
            typeof model.extraParams?.reasoning_budget_tokens === "number"
              ? model.extraParams.reasoning_budget_tokens
              : undefined,
        }
      : config.generation_config;
  const capability = model?.reasoningCapability;
  const budgetControl =
    capability?.status === "supported"
      ? capability.controls?.find((control) => control.type === "budget_tokens")
      : undefined;
  const effortControl =
    capability?.status === "supported"
      ? capability.controls?.find((control) => control.type === "effort")
      : undefined;
  const levels =
    effortControl?.type === "effort"
      ? effortControl.values.filter(isReasoningEffort)
      : capability?.status === "supported"
        ? capability.levels.filter(isReasoningEffort)
        : [];
  // Unknown capabilities never invent an effort; auto keeps provider defaults.
  const effort = generation.thinking_effort;
  const defaultCandidates: (ReasoningEffort | null | undefined)[] = [
    model.defaultReasoningEffort,
    DEFAULT_REASONING_EFFORT,
  ];
  const resolvedEffort = budgetControl
    ? "auto"
    : effort === "auto" || (effort && levels.includes(effort))
      ? effort
      : (defaultCandidates.find(
          (candidate) =>
            candidate === "auto" ||
            (candidate != null && levels.includes(candidate))
        ) ?? DEFAULT_REASONING_EFFORT);
  const enabled =
    capability?.status === "supported" ? generation.deep_thinking : false;
  const rawBudget = generation.reasoning_budget_tokens;
  const budget =
    budgetControl?.type === "budget_tokens"
      ? rawBudget && rawBudget > 0
        ? Math.min(budgetControl.max, Math.max(budgetControl.min, rawBudget))
        : 0
      : undefined;
  if (
    modelId === config.model_id &&
    resolvedEffort === effort &&
    enabled === config.generation_config.deep_thinking &&
    budget === rawBudget
  )
    return config;
  return {
    ...config,
    model_id: modelId,
    generation_config: {
      ...generation,
      thinking_effort: resolvedEffort,
      deep_thinking: enabled,
      reasoning_budget_tokens: budget,
    },
  };
}

export const deriveModelOptions = (
  agent: Agent | PublishedAgent,
  availableModels: readonly CatalogModelOption[],
  scope: ModelSelectionScope = "agent"
): readonly SelectorModelOption[] => {
  const typedAgent = agent as PublishedAgent;
  const toSelectorModel = (
    id: string,
    fallbackName: string
  ): SelectorModelOption => {
    const model = availableModels.find(
      (item) =>
        String(item.id) === id || item.name === id || item.displayName === id
    );
    if (model?.profileSchemaVersion) {
      return { id, name: fallbackName, profileSchemaVersion: model.profileSchemaVersion,
        agentParameterDefaults: scope === "agent" ? agentParameterValues({ ...typedAgent.model_params_override?.[id] }) : {} };
    }
    const extra =
      scope === "agent"
        ? typedAgent.model_params_override?.[id]?.extra_params
        : undefined;
    const capability = model?.reasoningCapability;
    const effortControl =
      capability?.status === "supported"
        ? capability.controls?.find((control) => control.type === "effort")
        : undefined;
    const levels =
      effortControl?.type === "effort"
        ? effortControl.values.filter(isReasoningEffort)
        : capability?.status === "supported"
          ? capability.levels.filter(isReasoningEffort)
          : [];
    const budgetControl =
      capability?.status === "supported"
        ? capability.controls?.find(
            (control) => control.type === "budget_tokens"
          )
        : undefined;
    const supportsBudget = budgetControl?.type === "budget_tokens";
    const effortLevels = [
      "auto",
      ...levels.filter((level) => level !== "auto"),
    ] as ReasoningEffort[];
    const supportsEffort = !supportsBudget && levels.length > 0;
    const snapshotEffort =
      typeof extra?.reasoning_effort === "string"
        ? (extra.reasoning_effort as ReasoningEffort)
        : undefined;
    const defaultCandidates: (ReasoningEffort | null | undefined)[] = [
      snapshotEffort,
      model?.defaultReasoningEffort,
      DEFAULT_REASONING_EFFORT,
    ];
    const defaultEffort =
      defaultCandidates.find(
        (candidate) => candidate != null && effortLevels.includes(candidate)
      ) ?? undefined;
    return {
      id,
      name: fallbackName,
      reasoningCapability: capability,
      defaultDeepThinking:
        typeof extra?.enable_thinking === "boolean"
          ? extra.enable_thinking
          : (model?.enableThinking ?? false),
      ...(supportsEffort
        ? {
            efforts: effortLevels.map((level) => ({ id: level, name: level })),
            defaultEffort,
          }
        : {}),
      ...(supportsBudget && budgetControl?.type === "budget_tokens"
        ? {
            budgetTokens: { min: budgetControl.min, max: budgetControl.max },
            defaultBudgetTokens:
              typeof extra?.reasoning_budget_tokens === "number"
                ? extra.reasoning_budget_tokens
                : typeof model?.extraParams?.reasoning_budget_tokens ===
                    "number"
                  ? model.extraParams.reasoning_budget_tokens
                  : undefined,
          }
        : {}),
    };
  };

  if (scope === "tenant") {
    return availableModels
      .filter(
        (model) => model.type === "llm" && model.connect_status === "available"
      )
      .map((model) =>
        toSelectorModel(String(model.id), model.displayName || model.name)
      );
  }

  const { model_ids, model_names } = typedAgent;

  if (
    model_ids &&
    model_ids.length > 0 &&
    model_names &&
    model_names.length > 0
  ) {
    const configuredModels = model_ids.map((id, index) =>
      toSelectorModel(String(id), model_names[index] || `Model ${id}`)
    );
    const availableModelIds = new Set(
      availableModels
        .filter(
          (model) =>
            model.type === "llm" && model.connect_status === "available"
        )
        .map((model) => String(model.id))
    );
    return configuredModels.filter((model) => availableModelIds.has(model.id));
  }

  const modelName = (typedAgent as unknown as { model_name?: string })
    .model_name;
  const modelIsAvailable = availableModels.some(
    (model) =>
      model.type === "llm" &&
      model.connect_status === "available" &&
      (model.displayName === modelName || model.name === modelName)
  );
  if (modelName && modelIsAvailable) {
    const model = availableModels.find(
      (item) => item.displayName === modelName || item.name === modelName
    );
    return [toSelectorModel(String(model?.id ?? modelName), modelName)];
  }

  const singleModel = (typedAgent as unknown as { model?: string }).model;
  const singleModelIsAvailable = availableModels.some(
    (model) =>
      model.type === "llm" &&
      model.connect_status === "available" &&
      (model.displayName === singleModel || model.name === singleModel)
  );
  if (singleModel && singleModelIsAvailable) {
    const model = availableModels.find(
      (item) => item.displayName === singleModel || item.name === singleModel
    );
    return [toSelectorModel(String(model?.id ?? singleModel), singleModel)];
  }

  return [];
};
