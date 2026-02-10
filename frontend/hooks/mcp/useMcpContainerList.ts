import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getMcpContainers } from "@/services/mcpService";
import { McpContainer } from "@/types/agentConfig";

export const MCP_CONTAINERS_QUERY_KEY = ["mcp", "containers"] as const;

export function useMcpContainerList(options?: { enabled?: boolean; staleTime?: number; tenantId?: string | null }) {
  const queryClient = useQueryClient();

  const fetchContainerList = useCallback(async () => {
    const res = await getMcpContainers(options?.tenantId);
    if (!res || !res.success) {
      throw new Error(res?.message || "Failed to load MCP container list");
    }
    return res;
  }, [options?.tenantId]);

  const query = useQuery({
    queryKey: [...MCP_CONTAINERS_QUERY_KEY, options?.tenantId],
    queryFn: fetchContainerList,
    staleTime: options?.staleTime ?? 60_000,
    enabled: options?.enabled ?? true,
  });

  const containerList = (query.data?.data ?? []) as McpContainer[];

  return {
    ...query,
    containerList,
    invalidate: () => queryClient.invalidateQueries({ queryKey: MCP_CONTAINERS_QUERY_KEY }),
  };
}

