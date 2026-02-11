import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AgentVersionDetail, fetchAgentVersionDetail, type AgentVersion } from "@/services/agentVersionService";


/**
 * Hook to fetch agent version info using React Query
 * @param options - Configuration options including agentId, versionNo and query settings
 * @returns Query result containing version data and utilities
 */
export function useAgentVersionDetail(agentId: number | null, versionNo: number | null) {

  const queryClient = useQueryClient();

  const isEnabled = agentId !== undefined && agentId !== null && versionNo !== undefined && versionNo !== null;

  const query = useQuery({
    queryKey: ["agentVersionDetail", agentId, versionNo],
    queryFn: async () => {
      if (agentId === undefined || agentId === null) {
        throw new Error("Agent ID is required");
      }
      if (versionNo === undefined || versionNo === null) {
        throw new Error("Version number is required");
      }
      const res = await fetchAgentVersionDetail(agentId, versionNo);
      if (!res.success) {
        throw new Error(res.message || "Failed to fetch agent version detail");
      }
      return res.data as AgentVersionDetail;
    },
    staleTime: 0,  // 改为 0，确保每次都重新获取
    gcTime: 0,  // 缓存立即过期
    enabled: isEnabled,
  });

  const agentVersionDetail = query.data ?? null;

  return {
    ...query,
    agentVersionDetail,
    invalidate: () =>
      queryClient.invalidateQueries({ queryKey: ["agentVersionDetail", agentId, versionNo] }),
  };
}
