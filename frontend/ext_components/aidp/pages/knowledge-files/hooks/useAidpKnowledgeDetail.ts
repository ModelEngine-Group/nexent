import { useMutation, useQuery } from "@tanstack/react-query";
import type { AidpSetPermissionPayload } from "@/ext_components/aidp/shared/types/management";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import log from "@/lib/logger";

export const useAidpKnowledgeDetail = (id: string) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [...scope.key, "detail", id],
    queryFn: async ({ signal }) => {
      try {
        return await aidpKnowledgeService.getKb(id, signal);
      } catch (error) {
        if (!signal.aborted)
          log.error("Failed to load AIDP knowledge base detail:", {
            id,
            error,
          });
        throw error;
      }
    },
    enabled: scope.enabled && !!id,
    staleTime: 30_000,
    retry: false,
  });
};

export const useSaveAidpKnowledgeSettings = () =>
  useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: AidpSetPermissionPayload;
    }) => aidpKnowledgeService.setPermission(id, payload),
    retry: false,
  });
