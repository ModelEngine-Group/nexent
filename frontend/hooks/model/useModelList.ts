import { useQuery, useQueryClient } from "@tanstack/react-query";
import { modelService } from "@/services/modelService";
import { ModelOption } from "@/types/modelConfig";
import { useMemo } from "react";
import { MODEL_TYPES } from "@/const/modelConfig";
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

	const vlmModels = useMemo(() => {
		return models.filter((model) => model.type === "vlm");
	}, [models]);

	const availableVlmModels = useMemo(() => {
		return models.filter((model) => model.type === "vlm" && model.connect_status === "available");
	}, [models]);

	const imageUnderstandingModels = useMemo(() => {
		return models.filter((model) => model.type === MODEL_TYPES.IMAGE_UNDERSTANDING);
	}, [models]);

	const availableImageUnderstandingModels = useMemo(() => {
		return models.filter((model) => model.type === MODEL_TYPES.IMAGE_UNDERSTANDING && model.connect_status === "available");
	}, [models]);

	const imageGenerationModels = useMemo(() => {
		return models.filter((model) => model.type === "image_generation");
	}, [models]);

	const availableImageGenerationModels = useMemo(() => {
		return models.filter((model) => model.type === "image_generation" && model.connect_status === "available");
	}, [models]);

	const videoUnderstandingModels = useMemo(() => {
		return models.filter((model) => model.type === "video_understanding");
	}, [models]);

	const availableVideoUnderstandingModels = useMemo(() => {
		return models.filter((model) => model.type === "video_understanding" && model.connect_status === "available");
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
		imageUnderstandingModels,
		availableImageUnderstandingModels,
		imageGenerationModels,
		availableImageGenerationModels,
		videoUnderstandingModels,
		availableVideoUnderstandingModels,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["models"] }),
	};
}
