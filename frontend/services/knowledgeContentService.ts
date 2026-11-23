// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import {
  isKnowledgeFileReference,
  isKnowledgeLegacyImageReference,
  isKnowledgeObjectReference,
} from "@/lib/knowledgeReference";
import type { KnowledgeContentRequest } from "@/types/knowledgeReference";

/** Own one bounded read, including response bytes, without retrying failed reads. */
export async function fetchKnowledgeContent(
  reference: KnowledgeContentRequest,
  signal?: AbortSignal
): Promise<Blob> {
  const { image_ref, ...file } = reference;
  if (
    !isKnowledgeLegacyImageReference(reference) &&
    (!isKnowledgeFileReference(file) ||
      (image_ref !== undefined && !isKnowledgeObjectReference(image_ref)))
  ) {
    throw new TypeError("Invalid knowledge content reference");
  }
  signal?.throwIfAborted();
  const controller = new AbortController();
  const cancel = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(
    () =>
      controller.abort(
        new DOMException("Knowledge content read timed out", "TimeoutError")
      ),
    12000
  );
  let onAbort: () => void = () => {};
  const aborted = new Promise<never>((_resolve, reject) => {
    onAbort = () => reject(controller.signal.reason);
    controller.signal.addEventListener("abort", onAbort, { once: true });
  });
  try {
    return await Promise.race([
      (async () => {
        const response = await fetchWithErrorHandling(
          API_ENDPOINTS.storage.knowledgeContent,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reference),
            signal: controller.signal,
            cache: "no-store",
          }
        );
        controller.signal.throwIfAborted();
        return await response.blob();
      })(),
      aborted,
    ]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
    controller.signal.removeEventListener("abort", onAbort);
  }
}
