import { useCallback, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import type {
  AidpKnowledgeBaseItem,
  AidpKnowledgeBaseListResponse,
} from "@/types/agentConfig";
import aidpKnowledgeService from "../services/aidpKnowledgeService";
import type { AidpCreateKbPayload } from "../services/aidpKnowledgeService";

/** Scope permission-sensitive caches to the current tenant and account. */
const useAidpQueryScope = () => {
  const { user } = useAuthorizationContext();
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const tenantId = user?.tenantId ?? null;
  const userId = user?.id ?? null;
  const key = useMemo(
    () => ["aidpKnowledge", tenantId, userId] as const,
    [tenantId, userId]
  );
  return { key, enabled: !!user && isDeploymentReady && enableAidpKnowledge };
};

export const useAidpKnowledgeList = (
  page: number,
  pageSize: number,
  keyword: string,
  enabled = true
) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [...scope.key, "list", { page, pageSize, keyword }],
    queryFn: () => aidpKnowledgeService.listKbs(page, pageSize, keyword),
    enabled: scope.enabled && enabled,
    staleTime: 30_000,
    refetchOnMount: "always",
    retry: false,
  });
};

export const useAidpModels = () => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [...scope.key, "models", "KnowledgeBase"],
    queryFn: () => aidpKnowledgeService.listModels("", "KnowledgeBase"),
    enabled: scope.enabled,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
};

export const useAidpGraphTemplate = (
  language: "chinese" | "english",
  enabled: boolean
) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [...scope.key, "graphTemplate", language],
    queryFn: () => aidpKnowledgeService.graphTemplate(language),
    enabled: scope.enabled && enabled,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
};

export const useAidpKnowledgeCache = () => {
  const { key } = useAidpQueryScope();
  const queryClient = useQueryClient();
  const refreshLists = useCallback(
    () => queryClient.invalidateQueries({ queryKey: [...key, "list"] }),
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

export const useCreateAidpKnowledgeBase = () => {
  const { refreshLists } = useAidpKnowledgeCache();
  return useMutation({
    mutationFn: (payload: AidpCreateKbPayload) =>
      aidpKnowledgeService.createKb(payload),
    onSuccess: () => refreshLists(),
    retry: false,
  });
};

export const useDeleteAidpKnowledgeBase = () => {
  const { key } = useAidpQueryScope();
  const queryClient = useQueryClient();
  const { refreshLists } = useAidpKnowledgeCache();
  return useMutation({
    mutationFn: (id: string) => aidpKnowledgeService.deleteKb(id),
    onSuccess: async (_result, id) => {
      queryClient.removeQueries({ queryKey: [...key, "detail", id] });
      await refreshLists();
    },
    retry: false,
  });
};
