import type { KnowledgeBase } from "@/types/knowledgeBase";

export const isMultimodalConstraintMismatch = (
  kb: KnowledgeBase,
  toolMultimodal: boolean | null
): boolean => {
  const kbIsMultimodal = Boolean(kb.is_multimodal);
  return (
    toolMultimodal !== null &&
    ((toolMultimodal && !kbIsMultimodal) || (!toolMultimodal && kbIsMultimodal))
  );
};

/**
 * Check whether a knowledge base is compatible with the configured embedding models.
 * String args must be model display names (matching kb.embeddingModel / display_name).
 */
export const isEmbeddingModelCompatible = (
  kb: KnowledgeBase,
  currentEmbeddingModel: string | null,
  currentMultiEmbeddingModel: string | null,
  currentEmbeddingModelId: number | null = null,
  currentMultiEmbeddingModelId: number | null = null
): boolean => {
  const configuredModelId = kb.is_multimodal
    ? currentMultiEmbeddingModelId
    : currentEmbeddingModelId;

  if (kb.embeddingModelId != null && configuredModelId != null) {
    return kb.embeddingModelId === configuredModelId;
  }

  if (kb.is_multimodal) {
    if (!currentMultiEmbeddingModel) {
      return true;
    }
    if (
      kb.embeddingModel &&
      kb.embeddingModel !== "unknown" &&
      kb.embeddingModel !== currentMultiEmbeddingModel
    ) {
      return false;
    }
    return true;
  }

  if (!currentEmbeddingModel) {
    return true;
  }

  if (
    kb.embeddingModel &&
    kb.embeddingModel !== "unknown" &&
    kb.embeddingModel !== currentEmbeddingModel
  ) {
    return false;
  }

  return true;
};

export const getKnowledgeBaseEmbeddingIdentity = (
  kb: KnowledgeBase
): string | null => {
  if (kb.embeddingModelId != null) {
    return `id:${kb.embeddingModelId}`;
  }

  if (!kb.embeddingModel || kb.embeddingModel === "unknown") {
    return null;
  }

  const modelType = kb.is_multimodal ? "multi_embedding" : "embedding";
  return `${modelType}:${kb.embeddingModel}`;
};
