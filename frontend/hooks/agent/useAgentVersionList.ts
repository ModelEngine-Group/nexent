import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAgentVersionList,
  type AgentVersion,
} from "@/services/agentVersionService";

/**
 * Hook to fetch agent version list using React Query
 * @param agentId The agent ID to fetch versions for
 * @param tenantId optional tenant ID for filtering
 * @returns Query result containing version list data and utilities
 */
export function useAgentVersionList(agentId: number | null, tenantId?: string) {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["agentVersions", agentId, tenantId],
    queryFn: async () => {
      if (agentId === undefined || agentId === null) {
        throw new Error("Agent ID is required");
      }
      const res = await fetchAgentVersionList(agentId, tenantId);
      if (!res.success) {
        throw new Error(res.message || "Failed to fetch agent versions");
      }
      return res.data;
    },
    staleTime: 60_000,
    enabled: agentId !== undefined && agentId !== null,
  });

  const agentVersionList = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  return {
    ...query,
    agentVersionList,
    total,
    invalidate: () =>
      queryClient.invalidateQueries({ queryKey: ["agentVersions", agentId, tenantId] }),
  };
}
