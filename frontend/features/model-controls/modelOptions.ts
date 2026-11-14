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

export type ModelSelectionScope = "agent" | "tenant";

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
      return {
        id,
        name: fallbackName,
        connectStatus: model.connect_status,
        profileSchemaVersion: model.profileSchemaVersion,
        agentParameterDefaults:
          scope === "agent"
            ? agentParameterValues({
                ...typedAgent.model_params_override?.[id],
              })
            : {},
      };
    }
    const extra =
      scope === "agent"
        ? typedAgent.model_params_override?.[id]?.extra_params
        : undefined;
    const sampling =
      scope === "agent" ? typedAgent.model_params_override?.[id] : undefined;
    const temperature =
      sampling?.temperature ??
      model?.temperature ??
      model?.effectiveSampling?.temperature;
    const topP =
      sampling?.top_p ?? model?.topP ?? model?.effectiveSampling?.top_p;
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
      connectStatus: model?.connect_status,
      ...(temperature != null || topP != null
        ? {
            defaultSampling: {
              ...(temperature != null ? { temperature } : {}),
              ...(topP != null ? { top_p: topP } : {}),
            },
          }
        : {}),
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
      .filter((model) => model.type === "llm")
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
        .filter((model) => model.type === "llm")
        .map((model) => String(model.id))
    );
    return configuredModels.filter((model) => availableModelIds.has(model.id));
  }

  const modelName = (typedAgent as unknown as { model_name?: string })
    .model_name;
  const modelIsAvailable = availableModels.some(
    (model) =>
      model.type === "llm" &&
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
