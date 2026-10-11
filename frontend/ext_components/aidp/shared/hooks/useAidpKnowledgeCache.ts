import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type {
  AidpKnowledgeBaseItem,
  AidpKnowledgeBaseListResponse,
} from "../types/knowledge";
import aidpKnowledgeService from "../services/aidpKnowledgeService";
import { useAidpQueryScope } from "./useAidpQueryScope";

export const useAidpKnowledgeCache = () => {
  const { key } = useAidpQueryScope();
  const queryClient = useQueryClient();
  const refreshLists = useCallback(
    () =>
      queryClient.invalidateQueries(
        { queryKey: [...key, "list"] },
        { cancelRefetch: false }
      ),
    [key, queryClient]
  );
  const updateKnowledgeBase = useCallback(
    (updated: AidpKnowledgeBaseItem) => {
      queryClient.setQueriesData<AidpKnowledgeBaseListResponse>(
        { queryKey: [...key, "list"] },
        (current) =>
          current && {
            ...current,
            value: current.value.map((item) =>
              item.kds_id === updated.kds_id ? { ...item, ...updated } : item
            ),
          }
      );
      queryClient.removeQueries({
        queryKey: [...key, "detail", updated.kds_id],
      });
    },
    [key, queryClient]
  );
  const fetchKnowledgeBase = useCallback(
    (id: string) =>
      queryClient.fetchQuery({
        queryKey: [...key, "detail", id],
        queryFn: () => aidpKnowledgeService.getKb(id),
        staleTime: 0,
        retry: false,
      }),
    [key, queryClient]
  );
  return { refreshLists, updateKnowledgeBase, fetchKnowledgeBase };
};
