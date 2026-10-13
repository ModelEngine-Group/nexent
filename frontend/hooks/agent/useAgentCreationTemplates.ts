import { useQuery } from "@tanstack/react-query";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import type { Agent } from "@/types/agentConfig";
import { fetchAgentList } from "@/services/agentConfigService";

export function useAgentCreationTemplates(open: boolean) {
  const { user } = useAuthorizationContext();
  return useQuery<Agent[]>({
    queryKey: ["agents", "creationTemplates", user?.tenantId, user?.email],
    enabled: open && Boolean(user),
    retry: false,
    staleTime: 0,
    queryFn: async () => {
      const result = await fetchAgentList(user?.tenantId || undefined);
      if (!result.success)
        throw new Error(result.message || "Failed to load Agent templates");
      const agents: Agent[] = result.data || [];
      return agents.filter((agent) => agent.is_main_agent !== false);
    },
  });
}
