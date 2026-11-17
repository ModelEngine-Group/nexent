// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState } from "react";
import { fetchKnowledgeContent } from "@/services/knowledgeContentService";
import type { KnowledgeContentRequest } from "@/types/knowledgeReference";

/** Blob URLs belong to the mounted consumer, never to persisted conversation data. */
export function useKnowledgeContentUrl(reference?: KnowledgeContentRequest) {
  const key = reference ? JSON.stringify(reference) : undefined;
  const [state, setState] = useState<{
    key?: string;
    url?: string;
    error?: unknown;
    signal?: AbortSignal;
  }>({});
  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    let url: string | undefined;
    void fetchKnowledgeContent(
      JSON.parse(key) as KnowledgeContentRequest,
      controller.signal
    )
      .then((blob) => {
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(blob);
        setState({ key, url, signal: controller.signal });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setState({ key, error, signal: controller.signal });
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [key]);
  return state.key === key && !state.signal?.aborted
    ? { url: state.url, error: state.error }
    : {};
}
