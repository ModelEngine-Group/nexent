import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { modelService } from "@/services/modelService";
import { ModelOption } from "@/types/modelConfig";
import { useMemo } from "react";
const EMPTY_MODELS: ModelOption[] = [];
export function useModelList(options?: {
  enabled?: boolean;
  staleTime?: number;
}) {
  const { user } = useAuthorizationContext();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["models", user?.tenantId, user?.id],
    queryFn: async (): Promise<ModelOption[]> => {
      const models = await modelService.getAllModels();
      return models;
    },
    staleTime: options?.staleTime ?? 60_000, // 1 minute default
    enabled: (options?.enabled ?? true) && Boolean(user),
  });

  const models = query.data ?? EMPTY_MODELS;

  // Filter models by type for convenience
  const llmModels = useMemo(() => {
    return models.filter((model) => model.type === "llm");
  }, [models]);

  const availableModels = useMemo(() => {
    return models.filter((model) => model.connect_status === "available");
  }, [models]);

  const availableLlmModels = useMemo(() => {
    return models.filter(
      (model) => model.type === "llm" && model.connect_status === "available"
    );
  }, [models]);

  const embeddingModels = useMemo(() => {
    return models.filter((model) => model.type === "embedding");
  }, [models]);

  const availableEmbeddingModels = useMemo(() => {
    return models.filter(
      (model) =>
        model.type === "embedding" && model.connect_status === "available"
    );
  }, [models]);

  const vlmModels = useMemo(() => {
    return models.filter((model) => model.type === "vlm");
  }, [models]);

  const availableVlmModels = useMemo(() => {
    return models.filter(
      (model) => model.type === "vlm" && model.connect_status === "available"
    );
  }, [models]);

  return {
    ...query,
    models,
    llmModels,
    availableModels,
    availableLlmModels,
    embeddingModels,
    availableEmbeddingModels,
    vlmModels,
    availableVlmModels,
    invalidate: () => queryClient.invalidateQueries({ queryKey: ["models"] }),
  };
}
