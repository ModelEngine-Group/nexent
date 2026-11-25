// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";

import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";

/**
 * Full-tree file search for the top search box.
 *
 * Unlike `useAidpFolderTree`, this query never carries a folder path: AIDP's
 * `KnowledgeFiles` endpoint returns matches from the whole knowledge base.
 */
export const useAidpIngestedFileSearch = (
  id: string,
  page: number,
  pageSize: number,
  keyword: string,
  pollingPaused = false
) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [
      ...scope.key,
      "ingested-file-search",
      id,
      { page, pageSize, keyword },
    ],
    queryFn: ({ signal }) =>
      aidpKnowledgeService.listIngestedFilePage(
        id,
        page,
        pageSize,
        keyword,
        signal
      ),
    enabled: scope.enabled && !!id && keyword.trim().length > 0,
    staleTime: 10_000,
    refetchOnMount: "always",
    refetchOnWindowFocus: pollingPaused ? false : "always",
    retry: false,
  });
};
