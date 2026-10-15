// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Knowledge binding previews for deletion confirmation dialogs. */

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import type {
  KnowledgeReferencePreview,
  KnowledgeResourceProvider,
} from "@/types/knowledgeResource";

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
