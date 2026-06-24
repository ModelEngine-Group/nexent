import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import agentRepositoryService from "@/services/agentRepositoryService";
import type {
  AgentRepositoryListingListParams,
  AgentRepositoryListingCreatePayload,
  AgentRepositoryListingStatus,
  MineOwnershipFilter,
} from "@/types/agentRepository";

const QUERY_KEY = "agentRepositoryListings";
const DETAIL_QUERY_KEY = "agentRepositoryListingDetail";
const MY_EDITABLE_AGENTS_QUERY_KEY = "myEditableAgents";

export function useAgentRepositoryListings(
  params?: AgentRepositoryListingListParams,
  enabled = true
) {
  return useQuery({
    queryKey: [QUERY_KEY, params],
    queryFn: () => agentRepositoryService.fetchAgentRepositoryListings(params),
    staleTime: 60_000,
    enabled,
  });
}

export function useMyEditableAgents(
  ownership: MineOwnershipFilter = "all",
  enabled = true
) {
  return useQuery({
    queryKey: [MY_EDITABLE_AGENTS_QUERY_KEY, ownership],
    queryFn: () => agentRepositoryService.fetchMyEditableAgents({ ownership }),
    staleTime: 60_000,
    enabled,
  });
}

export function useAgentRepositoryListingDetail(
  agentRepositoryId: number | null,
  enabled = true
) {
  return useQuery({
    queryKey: [DETAIL_QUERY_KEY, agentRepositoryId],
    queryFn: () =>
      agentRepositoryService.fetchAgentRepositoryListingDetail(
        agentRepositoryId as number
      ),
    staleTime: 60_000,
    enabled: enabled && agentRepositoryId != null,
  });
}

export function useUpdateAgentRepositoryStatus() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      agentRepositoryId,
      status,
    }: {
      agentRepositoryId: number;
      status: AgentRepositoryListingStatus;
    }) =>
      agentRepositoryService.updateAgentRepositoryStatus(
        agentRepositoryId,
        status
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
      queryClient.invalidateQueries({ queryKey: [MY_EDITABLE_AGENTS_QUERY_KEY] });
    },
  });
}

export function useCreateAgentRepositoryListing() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      agentId,
      versionNo,
      payload,
    }: {
      agentId: number;
      versionNo: number;
      payload: AgentRepositoryListingCreatePayload;
    }) =>
      agentRepositoryService.createAgentRepositoryListing(
        agentId,
        versionNo,
        payload
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
      queryClient.invalidateQueries({ queryKey: [MY_EDITABLE_AGENTS_QUERY_KEY] });
    },
  });
}
