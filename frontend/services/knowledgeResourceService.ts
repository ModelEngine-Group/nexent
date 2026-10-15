// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Knowledge resource status API client.
 *
 * The batch endpoint is read-only and returns one status entry per requested
 * identity. Callers must match responses by (provider, resource_id) instead of
 * relying on array order. The reference preview feeds the deletion
 * confirmation dialog; deletion itself cascades on the backend.
 */

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import type {
  KnowledgeReferencePreview,
  KnowledgeResourceContext,
  KnowledgeResourceProvider,
  KnowledgeResourceStatusEntry,
} from "@/types/knowledgeResource";

export const KNOWLEDGE_STATUS_BATCH_SIZE = 100;

export interface KnowledgeResourceStatusRequestItem {
  provider: KnowledgeResourceProvider;
  resource_id: string;
}

const chunkItems = <T>(items: T[], size: number): T[][] => {
  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
};

/**
 * Fetch statuses for the given resource identities.
 *
 * Throws when the request itself fails; the caller maps that to
 * `lookup_failed` for the currently selected items.
 */
export const getKnowledgeResourceStatuses = async (
  items: KnowledgeResourceStatusRequestItem[],
  context: KnowledgeResourceContext
): Promise<KnowledgeResourceStatusEntry[]> => {
  if (items.length === 0) {
    return [];
  }

  const deduped = Array.from(
    new Map(
      items.map((item) => [
        `${item.provider}:${String(item.resource_id)}`,
        { provider: item.provider, resource_id: String(item.resource_id) },
      ])
    ).values()
  );

  const results: KnowledgeResourceStatusEntry[] = [];
  for (const chunk of chunkItems(deduped, KNOWLEDGE_STATUS_BATCH_SIZE)) {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.knowledgeBase.statuses,
      {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ items: chunk, context }),
      }
    );
    const data = await response.json();
    const entries: KnowledgeResourceStatusEntry[] = data?.items ?? [];
    results.push(...entries);
  }
  log.debug(
    "Knowledge resource statuses fetched:",
    results.length,
    "context:",
    context.type
  );
  return results;
};

export const createUnavailableStatus = (
  provider: KnowledgeResourceProvider,
  resourceId: string
): KnowledgeResourceStatusEntry => ({
  provider,
  resource_id: String(resourceId),
  status: "lookup_failed",
  reason_code: "KNOWLEDGE_UNAVAILABLE_OR_INACCESSIBLE",
  retryable: true,
});

/**
 * Fetch the agents bound to one resource for the delete confirmation dialog.
 *
 * Returns null when the preview cannot be loaded; deletion still cascades on
 * the backend, so the caller only loses the extra notice in that case.
 */
export const previewKnowledgeReferences = async (
  provider: KnowledgeResourceProvider,
  resourceId: string
): Promise<KnowledgeReferencePreview | null> => {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.knowledgeBase.referencePreview,
      {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          provider,
          resource_id: String(resourceId),
        }),
      }
    );
    const data = await response.json();
    return {
      agents: Array.isArray(data?.agents) ? data.agents : [],
      hidden_agent_count: Number(data?.hidden_agent_count ?? 0),
      total_agent_count: Number(data?.total_agent_count ?? 0),
    };
  } catch (error) {
    log.warn("Knowledge reference preview unavailable:", error);
    return null;
  }
};
