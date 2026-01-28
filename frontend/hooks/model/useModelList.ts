import { useQuery, useQueryClient } from "@tanstack/react-query";
import { modelService } from "@/services/modelService";
import { ModelOption } from "@/types/modelConfig";
import { useMemo } from "react";
import { ConfigStore } from "@/lib/config";

export function useModelList(options?: { enabled?: boolean; staleTime?: number }) {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: ["models"],
		queryFn: async (): Promise<ModelOption[]> => {
			const models = await modelService.getAllModels();
			return models;
		},
		staleTime: options?.staleTime ?? 60_000, // 1 minute default
		enabled: options?.enabled ?? true,
	});

	const models = query.data ?? [];

	// Filter models by type for convenience
	const llmModels = useMemo(() => {
		return models.filter((model) => model.type === "llm");
	}, [models]);

	const availableModels = useMemo(() => {
		return models.filter((model) => model.connect_status === "available");
	}, [models]);

	const availableLlmModels = useMemo(() => {
		return models.filter((model) => model.type === "llm" && model.connect_status === "available");
	}, [models]);

	const embeddingModels = useMemo(() => {
		return models.filter((model) => model.type === "embedding");
	}, [models]);

	const availableEmbeddingModels = useMemo(() => {
		return models.filter((model) => model.type === "embedding" && model.connect_status === "available");
	}, [models]);

  // Get default LLM model from tenant configuration
  const defaultLlmModel = useMemo(() => {
    try {
      const configStore = ConfigStore.getInstance();
      const modelConfig = configStore.getModelConfig();
      const defaultModelName = modelConfig.llm?.modelName || modelConfig.llm?.displayName;

      if (defaultModelName) {
        // First try to find by name in available LLM models (should be available)
        let defaultModel = availableLlmModels.find(model =>
          model.name === defaultModelName ||
          model.displayName === defaultModelName
        );

        // If not found in available models, try all models but only if they're LLM type
        if (!defaultModel) {
          defaultModel = models.find(model =>
            model.type === "llm" && (
              model.name === defaultModelName ||
              model.displayName === defaultModelName
            )
          );
        }

        return defaultModel; // Return the found model or undefined if not found
      }

      // If no default configured, return undefined
      return undefined;
    } catch (error) {
      // Return undefined if config access fails
      return undefined;
    }
  }, [models, availableLlmModels]);


	return {
		...query,
		models,
		llmModels,
		availableModels,
		availableLlmModels,
		embeddingModels,
		availableEmbeddingModels,
    defaultLlmModel,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["models"] }),
	};
}
