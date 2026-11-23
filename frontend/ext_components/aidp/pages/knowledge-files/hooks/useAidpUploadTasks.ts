// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import log from "@/lib/logger";

/**
 * Upload-task history is separate from the ingested file list: it keeps rows
 * AIDP has not finished processing (or has failed), which is what makes the
 * status column and the retry action possible.
 *
 * Polling keeps running only while the tasks tab is visible and the upstream
 * stats report work still in flight (extracting or queued), so a settled
 * knowledge base stops polling after one idle refresh.
 */
export const useAidpUploadTasks = (
  id: string,
  page: number,
  pageSize: number,
  keyword: string,
  status: number,
  active: boolean
) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [
      ...scope.key,
      "upload-tasks",
      id,
      { page, pageSize, keyword, status },
    ],
    queryFn: async ({ signal }) => {
      try {
        return await aidpKnowledgeService.listUploadTasks(
          id,
          page,
          pageSize,
          keyword,
          status,
          signal
        );
      } catch (error) {
        if (!signal?.aborted)
          log.error("Failed to load AIDP upload tasks:", {
            id,
            page,
            status,
            error,
          });
        throw error;
      }
    },
    enabled: scope.enabled && !!id,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      if (!active) return false;
      const stats = query.state.data?.stats;
      if (!stats) return 10_000;
      return stats.extracting + stats.queued > 0 ? 10_000 : false;
    },
    refetchIntervalInBackground: false,
    retry: false,
  });
};
