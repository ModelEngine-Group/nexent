// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import type { AidpChunk } from "@/ext_components/aidp/shared/types/chunks";
import log from "@/lib/logger";

/**
 * Page through the chunks of one file.
 *
 * The query key carries the file UUID, so a late response for file A can only
 * update A's cache entry and never overwrites the file B page. No previous
 * data is kept, which is what clears the old list and selection on a switch.
 */
export const useAidpFileChunks = (
  id: string,
  fileUuid: string,
  page: number,
  pageSize: number
) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [...scope.key, "chunks", id, fileUuid, { page, pageSize }],
    queryFn: async ({ signal }) => {
      try {
        return await aidpKnowledgeService.listChunks(
          id,
          fileUuid,
          page,
          pageSize,
          signal
        );
      } catch (error) {
        if (!signal.aborted)
          log.error("Failed to load AIDP file chunks:", {
            id,
            fileUuid,
            page,
            error,
          });
        throw error;
      }
    },
    enabled: scope.enabled && !!id && !!fileUuid,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    retry: false,
  });
};

/** Search chunk content through the backend FusionSearch proxy. */
export const useAidpChunkSearch = (
  id: string,
  fileUuid: string,
  fileName: string,
  query: string,
  topk: number = 20
) => {
  const scope = useAidpQueryScope();
  const normalizedQuery = query.trim();
  return useQuery({
    queryKey: [
      ...scope.key,
      "chunk-search",
      id,
      fileUuid,
      fileName,
      normalizedQuery,
      topk,
    ],
    queryFn: async ({ signal }) => {
      try {
        return await aidpKnowledgeService.searchChunks(
          id,
          fileUuid,
          fileName,
          normalizedQuery,
          topk,
          signal
        );
      } catch (error) {
        if (!signal.aborted)
          log.error("Failed to search AIDP chunks:", {
            id,
            fileUuid,
            fileName,
            query: normalizedQuery,
            error,
          });
        throw error;
      }
    },
    enabled:
      scope.enabled && !!id && !!fileUuid && !!fileName && !!normalizedQuery,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
};

/** Read one chunk; only issued while a detail view is open. */
export const useAidpChunkDetail = (id: string, chunkId: number | null) => {
  const scope = useAidpQueryScope();
  return useQuery<AidpChunk>({
    queryKey: [...scope.key, "chunk-detail", id, chunkId],
    queryFn: async ({ signal }) => {
      try {
        return await aidpKnowledgeService.getChunk(
          id,
          chunkId as number,
          signal
        );
      } catch (error) {
        if (!signal.aborted)
          log.error("Failed to load AIDP chunk detail:", {
            id,
            chunkId,
            error,
          });
        throw error;
      }
    },
    enabled: scope.enabled && !!id && chunkId !== null,
    refetchOnWindowFocus: false,
    retry: false,
  });
};
