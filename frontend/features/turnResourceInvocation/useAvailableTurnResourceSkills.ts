import { useQuery } from "@tanstack/react-query";

import { fetchSkills } from "@/services/agentConfigService";
import type { Skill } from "@/types/agentConfig";

const TURN_RESOURCE_SKILLS_QUERY_KEY = ["turnResourceInvocation", "skills"];

export function useAvailableTurnResourceSkills() {
  return useQuery<Skill[]>({
    queryKey: TURN_RESOURCE_SKILLS_QUERY_KEY,
    queryFn: async () => {
      const result = await fetchSkills();
      if (!result.success) throw new Error(result.message);
      return result.data;
    },
    staleTime: 60_000,
  });
}
