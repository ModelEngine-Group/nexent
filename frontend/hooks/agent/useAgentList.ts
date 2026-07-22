import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAgentList as fetchAgentListService } from "@/services/agentConfigService";
import { useMemo } from "react";
import { Agent } from "@/types/agentConfig";

export function useAgentList(
  tenantId: string | null,
  options?: { includeOwnedNl2AgentDrafts?: boolean }
) {
  const queryClient = useQueryClient();
  // null = caller is waiting (e.g. tenant not selected); empty string = use auth tenant from backend
  const queryEnabled = tenantId !== null;
  const apiTenantId =
    tenantId !== null && tenantId.trim() !== "" ? tenantId : undefined;

  const query = useQuery({
    queryKey: [
      "agents",
      tenantId,
      options?.includeOwnedNl2AgentDrafts ?? false,
    ],
    queryFn: async () => {
      const res = await fetchAgentListService(
        apiTenantId,
        options?.includeOwnedNl2AgentDrafts ?? false
      );
      if (!res || !res.success) {
        throw new Error(res?.message || "Failed to fetch agents");
      }
      return res.data || [];
    },
    staleTime: 60_000,
    enabled: queryEnabled,
  });

  const agents = query.data ?? [];

  const availableAgents = useMemo(() => {
    return (agents as Agent[]).filter((a) => a.is_available !== false);
  }, [agents]);

  return {
    ...query,
    agents,
    availableAgents,
    invalidate: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
  };
}
