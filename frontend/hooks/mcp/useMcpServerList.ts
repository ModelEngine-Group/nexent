import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getMcpServerList } from "@/services/mcpService";
import { McpServer } from "@/types/agentConfig";

export const MCP_SERVERS_QUERY_KEY = ["mcp", "servers"] as const;

export function useMcpServerList(options?: { enabled?: boolean; staleTime?: number; tenantId?: string | null }) {
  const queryClient = useQueryClient();

  const fetchServerList = useCallback(async () => {
    const res = await getMcpServerList(options?.tenantId);
    if (!res || !res.success) {
      throw new Error(res?.message || "Failed to load MCP server list");
    }
    return res;
  }, [options?.tenantId]);

  const query = useQuery({
    queryKey: [...MCP_SERVERS_QUERY_KEY, options?.tenantId],
    queryFn: fetchServerList,
    staleTime: options?.staleTime ?? 60_000,
    enabled: options?.enabled ?? true,
  });

  const serverList = (query.data?.data ?? []) as McpServer[];
  const enableUploadImage = Boolean(query.data?.enable_upload_image);

  return {
    ...query,
    serverList,
    enableUploadImage,
    invalidate: () => queryClient.invalidateQueries({ queryKey: MCP_SERVERS_QUERY_KEY }),
  };
}

