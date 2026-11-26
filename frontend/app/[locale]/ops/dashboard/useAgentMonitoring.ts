// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useIsFetching, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAgentMonitoringSummary,
  getAgentMonitoringTrends,
} from "@/services/agentMonitoringService";
import type { AgentMonitoringSelection } from "@/types/agentMonitoring";

export function useAgentMonitoring(
  userId: string,
  userTenant: string,
  selection: AgentMonitoringSelection | null
) {
  const queryClient = useQueryClient();
  const queryKey = ["agentMonitoring", userId, userTenant, selection] as const;
  const fetching = useIsFetching({ queryKey }) > 0;
  const summary = useQuery({
    queryKey: [...queryKey, "summary"],
    queryFn: ({ signal }) => getAgentMonitoringSummary(selection!, signal),
    enabled: selection !== null,
  });
  const trends = useQuery({
    queryKey: [...queryKey, "trends"],
    queryFn: ({ signal }) => getAgentMonitoringTrends(selection!, signal),
    enabled: selection !== null,
  });
  return {
    summary,
    trends,
    fetching,
    queryKey,
    refresh: () => queryClient.refetchQueries({ queryKey, type: "active" }),
  };
}
