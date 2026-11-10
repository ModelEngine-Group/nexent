// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AgentVersionDetail,
  fetchAgentVersionDetail,
  type AgentVersion,
} from "@/services/agentVersionService";

/**
 * Hook to fetch agent version info using React Query
 * @param options - Configuration options including agentId, versionNo and query settings
 * @returns Query result containing version data and utilities
 */
export function useAgentVersionDetail(
  agentId: number | null,
  versionNo: number | null,
  enabled = true,
  cacheTime = 0
) {
  const queryClient = useQueryClient();

  const isEnabled =
    enabled &&
    agentId !== undefined &&
    agentId !== null &&
    versionNo !== undefined &&
    versionNo !== null;

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
    staleTime: cacheTime,
    gcTime: cacheTime,
    enabled: isEnabled,
  });

  const agentVersionDetail = query.data ?? null;

  return {
    ...query,
    agentVersionDetail,
    invalidate: () =>
      queryClient.invalidateQueries({
        queryKey: ["agentVersionDetail", agentId, versionNo],
      }),
  };
}
