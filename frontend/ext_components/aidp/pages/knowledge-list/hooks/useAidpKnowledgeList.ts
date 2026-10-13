import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { useAidpKnowledgeCache } from "@/ext_components/aidp/shared/hooks/useAidpKnowledgeCache";

export const useAidpKnowledgeList = (
  page: number,
  pageSize: number,
  keyword: string,
  enabled = true,
  pollingPaused = false
) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [...scope.key, "list", { page, pageSize, keyword }],
    queryFn: () => aidpKnowledgeService.listKbs(page, pageSize, keyword),
    enabled: scope.enabled && enabled,
    staleTime: 30_000,
    refetchOnMount: "always",
    refetchInterval: pollingPaused ? false : 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: pollingPaused ? false : "always",
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
