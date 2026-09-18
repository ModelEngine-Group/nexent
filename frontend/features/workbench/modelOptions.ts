import type { Agent, PublishedAgent } from "@/types/agentConfig";
import type { ModelOption as CatalogModelOption } from "@/types/modelConfig";

export type ModelSelectionScope = "agent" | "tenant";

export const deriveModelOptions = (
  agent: Agent | PublishedAgent,
  availableModels: readonly CatalogModelOption[],
  scope: ModelSelectionScope = "agent"
): readonly { id: string; name: string }[] => {
  if (scope === "tenant") {
    return availableModels
      .filter(
        (model) =>
          model.type === "llm" && model.connect_status === "available"
      )
      .map((model) => ({
        id: String(model.id),
        name: model.displayName || model.name,
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
    return [{ id: modelName, name: modelName }];
  }

  const singleModel = (typedAgent as unknown as { model?: string }).model;
  const singleModelIsAvailable = availableModels.some(
    (model) =>
      model.connect_status === "available" &&
      (model.displayName === singleModel || model.name === singleModel)
  );
  if (singleModel && singleModelIsAvailable) {
    return [{ id: singleModel, name: singleModel }];
  }

  return [];
};
