import type { Agent, PublishedAgent } from "@/types/agentConfig";
import type {
  ModelOption as CatalogModelOption,
  ReasoningEffort,
} from "@/types/modelConfig";
import type { ModelOption as SelectorModelOption } from "@/app/newchat/ui/model-selector";
import { DEFAULT_REASONING_EFFORT } from "@/const/modelConfig";
import type { WorkbenchSessionConfig } from "./types";

export type ModelSelectionScope = "agent" | "tenant";

/** Keep the model displayed in Workbench identical to the model sent at run time. */
export function withDefaultWorkbenchModel(
  config: WorkbenchSessionConfig,
  availableLlmModels: readonly Pick<CatalogModelOption, "id">[]
): WorkbenchSessionConfig {
  if (config.model_id != null || availableLlmModels.length === 0) return config;
  return { ...config, model_id: availableLlmModels[0].id };
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
    if (scope === "tenant" && !model?.reasoningCapability) {
      return { id, name: fallbackName, efforts: true };
    }
    const extra =
      scope === "agent"
        ? typedAgent.model_params_override?.[id]?.extra_params
        : undefined;
    const hasSnapshot =
      typeof extra?.enable_thinking === "boolean" ||
      typeof extra?.reasoning_effort === "string" ||
      typeof extra?.reasoning_budget_tokens === "number";
    const enabled = hasSnapshot
      ? extra?.enable_thinking === true ||
        (extra?.enable_thinking === undefined &&
          (typeof extra?.reasoning_effort === "string" ||
            typeof extra?.reasoning_budget_tokens === "number"))
      : model?.enableThinking === true;
    const capability = model?.reasoningCapability;
    const effortControl =
      capability?.status === "supported"
        ? capability.controls?.find((control) => control.type === "effort")
        : undefined;
    const levels =
      effortControl?.type === "effort"
        ? (effortControl.values as ReasoningEffort[])
        : capability?.status === "supported"
          ? capability.levels
          : [];
    const budgetControl =
      capability?.status === "supported"
        ? capability.controls?.find(
            (control) => control.type === "budget_tokens"
          )
        : undefined;
    const supportsBudget = enabled && budgetControl?.type === "budget_tokens";
    const effortLevels = [
      "auto",
      ...levels.filter((level) => level !== "auto"),
    ] as ReasoningEffort[];
    const supportsEffort =
      !supportsBudget && (scope === "tenant" || (enabled && levels.length > 0));
    if (scope === "tenant" && levels.length === 0) {
      effortLevels.push("low", "medium", "high");
    }
    const snapshotEffort =
      typeof extra?.reasoning_effort === "string"
        ? (extra.reasoning_effort as ReasoningEffort)
        : undefined;
    const defaultCandidates: (ReasoningEffort | null | undefined)[] = [
      model?.defaultReasoningEffort,
      "auto",
      capability?.status === "supported" ? capability.default : undefined,
      DEFAULT_REASONING_EFFORT,
    ];
    const defaultEffort = hasSnapshot
      ? (snapshotEffort ?? "auto")
      : (defaultCandidates.find(
          (candidate) => candidate != null && effortLevels.includes(candidate)
        ) ?? undefined);
    return {
      id,
      name: fallbackName,
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
        .filter((model) => model.connect_status === "available")
        .map((model) => String(model.id))
    );
    return configuredModels.filter((model) => availableModelIds.has(model.id));
  }

  const modelName = (typedAgent as unknown as { model_name?: string })
    .model_name;
  const modelIsAvailable = availableModels.some(
    (model) =>
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
