// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";

import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import log from "@/lib/logger";

/**
 * One folder level. AIDP paginates the files server-side and returns the
 * direct subfolders alongside them, so paging/search must stay in this query
 * rather than filtering a previously loaded page in the browser.
 */
export const useAidpFolderTree = (
  id: string,
  folderPath: string,
  page: number,
  pageSize: number,
  keyword: string,
  pollingPaused = false
) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [
      ...scope.key,
      "folder-tree",
      id,
      { folderPath, page, pageSize, keyword },
    ],
    queryFn: async ({ signal }) => {
      try {
        return await aidpKnowledgeService.getFolderTree(
          id,
          folderPath,
          page,
          pageSize,
          keyword,
          signal
        );
      } catch (error) {
        if (!signal.aborted) {
          log.error("Failed to load AIDP folder tree:", {
            id,
            folderPath,
            page,
            error,
          });
        }
        throw error;
      }
    },
    enabled: scope.enabled && !!id,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchInterval: pollingPaused ? false : 30_000,
    refetchIntervalInBackground: false,
    retry: false,
  });
};
