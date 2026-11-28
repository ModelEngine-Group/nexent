// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import aidpSensitiveWordService from "@/ext_components/aidp/shared/services/aidpSensitiveWordService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import type {
  AidpSensitiveWordMode,
  AidpSensitiveWordPayload,
  AidpSensitiveWordUpdatePayload,
} from "@/ext_components/aidp/shared/types/sensitiveWord";

export interface AidpSensitiveWordDeleteFailure {
  id: string;
  reason: string;
}

export const useAidpSensitiveWordList = (
  kdsId: string,
  page: number,
  pageSize: number,
  keyword: string,
  mode?: AidpSensitiveWordMode
) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [
      ...scope.key,
      "sensitive-words",
      kdsId,
      { page, pageSize, keyword, mode },
    ],
    queryFn: () =>
      aidpSensitiveWordService.list(kdsId, page, pageSize, keyword, mode),
    enabled: scope.enabled && Boolean(kdsId),
    staleTime: 15_000,
    refetchOnMount: "always",
    retry: false,
  });
};

const useInvalidateSensitiveWords = (kdsId: string) => {
  const { key } = useAidpQueryScope();
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({
      queryKey: [...key, "sensitive-words", kdsId],
    });
};

export const useCreateAidpSensitiveWord = (kdsId: string) => {
  const invalidate = useInvalidateSensitiveWords(kdsId);
  return useMutation({
    mutationFn: (payload: AidpSensitiveWordPayload) =>
      aidpSensitiveWordService.create(kdsId, payload),
    onSuccess: invalidate,
    retry: false,
  });
};

export const useUpdateAidpSensitiveWord = (kdsId: string) => {
  const invalidate = useInvalidateSensitiveWords(kdsId);
  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: AidpSensitiveWordUpdatePayload;
    }) => aidpSensitiveWordService.update(kdsId, id, payload),
    onSuccess: invalidate,
    retry: false,
  });
};

/**
 * Delete the selected IDs one by one because AIDP only exposes a single-word
 * DELETE. Every failure keeps its id and upstream reason so the caller can
 * report the exact words that remained.
 */
export const useDeleteAidpSensitiveWords = (kdsId: string) => {
  const invalidate = useInvalidateSensitiveWords(kdsId);
  return useMutation({
    mutationFn: async (ids: string[]) => {
      const failed: AidpSensitiveWordDeleteFailure[] = [];
      let succeeded = 0;
      for (const id of ids) {
        try {
          await aidpSensitiveWordService.remove(kdsId, id);
          succeeded += 1;
        } catch (error) {
          failed.push({
            id,
            reason: error instanceof Error ? error.message : "",
          });
        }
      }
      return { succeeded, failed };
    },
    onSettled: invalidate,
    retry: false,
  });
};
