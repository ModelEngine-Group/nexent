import { useQuery, useQueryClient } from "@tanstack/react-query";

import { promptTemplateService } from "@/services/promptTemplateService";
import { PromptTemplate } from "@/types/agentConfig";

export function usePromptTemplateList() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["promptTemplates"],
    queryFn: async (): Promise<PromptTemplate[]> => {
      return promptTemplateService.list();
    },
    staleTime: 60_000,
  });

  return {
    ...query,
    templates: query.data ?? [],
    invalidate: () => queryClient.invalidateQueries({ queryKey: ["promptTemplates"] }),
  };
}
