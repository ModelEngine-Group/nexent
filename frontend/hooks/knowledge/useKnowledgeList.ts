import { useQuery } from "@tanstack/react-query";
import knowledgeBaseService from "@/services/knowledgeBaseService";

export function useKnowledgeList(tenantId: string | null) {
  return useQuery({
    queryKey: ["knowledgeBases", tenantId],
    queryFn: () => knowledgeBaseService.getKnowledgeBasesInfo(),
    enabled: !!tenantId,
    staleTime: 1000 * 60 * 5, // Cache for 5 minutes
    refetchOnMount: "always",
  });
}
