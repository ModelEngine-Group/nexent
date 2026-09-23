import type { Agent, PublishedAgent } from "@/types/agentConfig";
import type { ModelOption as CatalogModelOption } from "@/types/modelConfig";
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
): readonly { id: string; name: string; efforts: boolean }[] => {
  if (scope === "tenant") {
    return availableModels
      .filter(
        (model) => model.type === "llm" && model.connect_status === "available"
      )
      .map((model) => ({
        id: String(model.id),
        name: model.displayName || model.name,
        efforts: true,
      }));
  }

  const typedAgent = agent as PublishedAgent;
  const { model_ids, model_names } = typedAgent;

  if (
    model_ids &&
    model_ids.length > 0 &&
    model_names &&
    model_names.length > 0
  ) {
    const configuredModels = model_ids.map((id, index) => ({
      id: String(id),
      name: model_names[index] || `Model ${id}`,
      efforts: true,
    }));
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
    return [{ id: modelName, name: modelName, efforts: true }];
  }

  const singleModel = (typedAgent as unknown as { model?: string }).model;
  const singleModelIsAvailable = availableModels.some(
    (model) =>
      model.connect_status === "available" &&
      (model.displayName === singleModel || model.name === singleModel)
  );
  if (singleModel && singleModelIsAvailable) {
    return [{ id: singleModel, name: singleModel, efforts: true }];
  }

  return [];
};
