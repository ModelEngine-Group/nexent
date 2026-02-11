import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAgentVersion, type AgentVersion } from "@/services/agentVersionService";


/**
 * Hook to fetch agent version info using React Query
 * @param options - Configuration options including agentId, versionNo and query settings
 * @returns Query result containing version data and utilities
 */
export function useAgentVersion(agentId: number | null, versionNo: number) {

  const queryClient = useQueryClient();

  const isEnabled = agentId !== undefined && agentId !== null && versionNo !== undefined && versionNo !== null;

  const query = useQuery({
    queryKey: ["agentVersion", agentId, versionNo],
    queryFn: async () => {
      console.log("queryFn executed! agentId:", agentId, "versionNo:", versionNo); // 调试日志
      if (agentId === undefined || agentId === null) {
        throw new Error("Agent ID is required");
      }
      if (versionNo === undefined || versionNo === null) {
        throw new Error("Version number is required");
      }
      const res = await fetchAgentVersion(agentId, versionNo);

      if (!res.success) {
        throw new Error(res.message || "Failed to fetch agent version info");
      }
      return res.data as AgentVersion;
    },
    staleTime: 0,  // 改为 0，确保每次都重新获取
    gcTime: 0,  // 缓存立即过期
    enabled: isEnabled,
  });

  const agentVersionInfo = query.data ?? null;

  return {
    ...query,
    agentVersionInfo,
    invalidate: () =>
      queryClient.invalidateQueries({ queryKey: ["agentVersion", agentId, versionNo] }),
  };
}
