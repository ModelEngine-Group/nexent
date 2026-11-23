"use client";

import { useCallback, useState } from "react";

/** Shared transient state for embedding configuration in knowledge selectors. */
export function useEmbeddingModelDialog() {
  const [embeddingModelDialogOpen, setEmbeddingModelDialogOpen] =
    useState(false);
  const [embeddingModelDialogData, setEmbeddingModelDialogData] = useState<{
    indexName: string;
    knowledgeName: string;
  } | null>(null);
  const [embeddingModelDialogMismatch, setEmbeddingModelDialogMismatch] =
    useState(false);
  const [configuringKbIds, setConfiguringKbIds] = useState<Set<string>>(
    new Set()
  );

  const resetEmbeddingModelDialog = useCallback(() => {
    setEmbeddingModelDialogOpen(false);
    setEmbeddingModelDialogData(null);
    setEmbeddingModelDialogMismatch(false);
    setConfiguringKbIds(new Set());
  }, []);

  return {
    setEmbeddingModelDialogOpen,
    setEmbeddingModelDialogData,
    setEmbeddingModelDialogMismatch,
    configuringKbIds,
    setConfiguringKbIds,
    resetEmbeddingModelDialog,
    embeddingModelDialogProps: {
      isOpen: embeddingModelDialogOpen,
      knowledgeBaseName: embeddingModelDialogData?.knowledgeName || "",
      indexName: embeddingModelDialogData?.indexName || "",
      isModelMismatch: embeddingModelDialogMismatch,
      kbIdsToUpdate: Array.from(configuringKbIds),
      onClose: resetEmbeddingModelDialog,
    },
  };
}
