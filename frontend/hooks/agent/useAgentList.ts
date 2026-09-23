import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAgentList as fetchAgentListService,
  fetchPagedAgentList,
  type AgentListFilters,
} from "@/services/agentConfigService";
import { useMemo } from "react";
import { Agent } from "@/types/agentConfig";

type UseAgentListInput = string | null | AgentListFilters;
const EMPTY_AGENTS: Agent[] = [];

const isLegacyInput = (input: UseAgentListInput): input is string | null =>
  typeof input === "string" || input === null;

export function useAgentList(input: UseAgentListInput) {
  const queryClient = useQueryClient();
  const legacyInput = isLegacyInput(input);
  const filters = legacyInput
    ? { tenantId: input, page: 1, pageSize: 20 }
    : input;
  // null = caller is waiting (e.g. tenant not selected); empty string = use auth tenant from backend
  const queryEnabled =
    filters.tenantId !== null &&
    (legacyInput || !("enabled" in filters) || filters.enabled !== false);
  const apiTenantId =
    filters.tenantId !== null && filters.tenantId?.trim() !== ""
      ? filters.tenantId
      : undefined;

  const query = useQuery({
    queryKey: ["agents", legacyInput ? "legacy" : filters],
    queryFn: async () => {
      if (!legacyInput) {
        const res = await fetchPagedAgentList(filters);
        if (!res.success) {
          throw new Error(res.message || "Failed to fetch agents");
        }
        return res.data;
      }
      const res = await fetchAgentListService(apiTenantId);
      if (!res || !res.success) {
        throw new Error(res?.message || "Failed to fetch agents");
      }
      const agents = res.data || [];
      return {
        agents,
        creatorCounts: undefined,
        pagination: {
          page: 1,
          pageSize: agents.length,
          total: agents.length,
          totalPages: agents.length ? 1 : 0,
        },
      };
    },
    staleTime: 60_000,
    enabled: queryEnabled,
  });

  const agents: Agent[] = query.data?.agents ?? EMPTY_AGENTS;

  const availableAgents = useMemo(() => {
    return (agents as Agent[]).filter((a) => a.is_available !== false);
  }, [agents]);

  return {
    ...query,
    agents,
    pagination: query.data?.pagination,
    creatorCounts: query.data?.creatorCounts,
    availableAgents,
    invalidate: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
  };
}
