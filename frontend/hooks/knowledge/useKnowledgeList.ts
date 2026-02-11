import { useQuery, useQueryClient } from "@tanstack/react-query";
import knowledgeBaseService from "@/services/knowledgeBaseService";

export function useKnowledgeList(tenantId: string | null) {
  const queryClient = useQueryClient();

  return useQuery({
    queryKey: ["knowledgeBases", tenantId],
    queryFn: async () => {
      const result = await knowledgeBaseService.getKnowledgeBasesInfo(false, true, tenantId ?? undefined);
      // Sort by updatedAt descending
      return result.knowledgeBases.sort((a, b) => {
        const dateA = a.updatedAt ? new Date(a.updatedAt).getTime() : 0;
        const dateB = b.updatedAt ? new Date(b.updatedAt).getTime() : 0;
        return dateB - dateA;
      });
    },
    enabled: !!tenantId,
    refetchOnMount: "always",
  });
}
