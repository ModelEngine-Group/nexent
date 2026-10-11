import { useQuery } from "@tanstack/react-query";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";

export const useAidpKnowledgeFiles = (
  id: string,
  page: number,
  pageSize: number,
  keyword: string
) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [...scope.key, "files", id, { page, pageSize, keyword }],
    queryFn: ({ signal }) =>
      aidpKnowledgeService.listDocs(id, page, pageSize, keyword, signal),
    enabled: scope.enabled && !!id,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    retry: false,
  });
};
