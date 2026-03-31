import { KnowledgeBase } from "@/types/knowledgeBase";

export const isMultimodalConstraintMismatch = (
  kb: KnowledgeBase,
  toolMultimodal: boolean | null
): boolean => {
  return (
    toolMultimodal !== null &&
    ((toolMultimodal && !kb.is_multimodal) ||
      (!toolMultimodal && kb.is_multimodal))
  );
};

export const isEmbeddingModelCompatible = (
  kb: KnowledgeBase,
  currentEmbeddingModel: string | null,
  currentMultiEmbeddingModel: string | null
): boolean => {
  if (kb.is_multimodal) {
    if (!currentMultiEmbeddingModel) {
      return false;
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
