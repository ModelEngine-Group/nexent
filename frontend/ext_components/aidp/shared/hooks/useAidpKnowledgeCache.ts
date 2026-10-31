import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { AidpKnowledgeBaseItem } from "../types/knowledge";
import type { AidpKbDetail } from "../types/management";
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
      queryClient.setQueryData<AidpKbDetail>(
        [...key, "detail", updated.kds_id],
        (current) => ({ ...current, ...updated })
      );
      void refreshLists();
    },
    [key, queryClient, refreshLists]
  );
  const fetchKnowledgeBase = useCallback(
    (id: string) =>
      queryClient.fetchQuery({
        queryKey: [...key, "detail", id],
        queryFn: ({ signal }) => aidpKnowledgeService.getKb(id, signal),
        staleTime: 30_000,
        retry: false,
      }),
    [key, queryClient]
  );
  return { refreshLists, updateKnowledgeBase, fetchKnowledgeBase };
};
