// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import type { AidpFileSummaryResponse } from "@/ext_components/aidp/shared/types/summary";
import log from "@/lib/logger";

/** A pending summary is polled at a low frequency; terminal states stop. */
const PENDING_SUMMARY_POLL_MS = 5000;

/**
 * Read one file's summary.
 *
 * The query only runs while the summary panel is mounted (the summary tab is
 * active and the knowledge base has summaries enabled), so switching tabs or
 * leaving the file detail stops both the request and the pending polling.
 */
export const useAidpFileSummary = (
  id: string,
  fileUuid: string,
  enabled: boolean,
  previewEnabled: boolean
) => {
  const scope = useAidpQueryScope();
  return useQuery<AidpFileSummaryResponse>({
    queryKey: [...scope.key, "file-summary", id, fileUuid],
    queryFn: async ({ signal }) => {
      try {
        return await aidpKnowledgeService.getFileSummary(id, fileUuid, signal);
      } catch (error) {
        if (!signal.aborted)
          log.error("Failed to load AIDP file summary:", {
            id,
            fileUuid,
            error,
          });
        throw error;
      }
    },
    enabled: scope.enabled && enabled && !!id && !!fileUuid,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      if (!previewEnabled) return false;
      const result = query.state.data?.result;
      const status = result?.summary_status?.toString().toLowerCase();
      // A pending status is explicit; an empty result with preview enabled is
      // also treated as still generating rather than as a failure.
      if (status === "pending") return PENDING_SUMMARY_POLL_MS;
      if (!status && !result?.summary_text) return PENDING_SUMMARY_POLL_MS;
      return false;
    },
    refetchIntervalInBackground: false,
    retry: false,
  });
};
