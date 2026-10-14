import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AidpKbDetail } from "@/ext_components/aidp/shared/types/management";
import log from "@/lib/logger";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";

export const useAidpKnowledgeFiles = (
  id: string,
  page: number,
  pageSize: number,
  keyword: string,
  pollingPaused = false
) => {
  const scope = useAidpQueryScope();
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: [...scope.key, "files", id, { page, pageSize, keyword }],
    queryFn: async ({ signal }) => {
      try {
        const result = await aidpKnowledgeService.listDocs(
          id,
          page,
          pageSize,
          keyword,
          signal
        );
        if (!keyword && result.total_reliable) {
          queryClient.setQueryData<AidpKbDetail>(
            [...scope.key, "detail", id],
            (current) =>
              current && {
                ...current,
                document_count: result.total_count,
              }
          );
        }
        return result;
      } catch (error) {
        if (!signal.aborted)
          log.error("Failed to load AIDP knowledge files:", {
            id,
            page,
            error,
          });
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
