import { useMutation, useQuery } from "@tanstack/react-query";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import type { AidpCreateKbPayload } from "@/ext_components/aidp/shared/types/management";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { useAidpKnowledgeCache } from "@/ext_components/aidp/shared/hooks/useAidpKnowledgeCache";

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

export const useCreateAidpKnowledgeBase = () => {
  const { refreshLists } = useAidpKnowledgeCache();
  return useMutation({
    mutationFn: (payload: AidpCreateKbPayload) =>
      aidpKnowledgeService.createKb(payload),
    onSuccess: () => refreshLists(),
    retry: false,
  });
};
