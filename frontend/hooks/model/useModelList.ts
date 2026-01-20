import { useQuery, useQueryClient } from "@tanstack/react-query";
import { modelService } from "@/services/modelService";
import { ModelOption } from "@/types/modelConfig";
import { useMemo } from "react";

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


  return {
    ...query,
    models,
    llmModels,
    availableModels,
    availableLlmModels,
    embeddingModels,
    availableEmbeddingModels,
    invalidate: () => queryClient.invalidateQueries({ queryKey: ["models"] }),
  };
}
