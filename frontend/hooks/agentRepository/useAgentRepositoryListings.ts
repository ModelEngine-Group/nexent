import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import agentRepositoryService from "@/services/agentRepositoryService";
import type {
  AgentRepositoryListingListParams,
  AgentRepositoryListingCreatePayload,
  AgentRepositoryListingStatus,
  MyEditableAgentListParams,
} from "@/types/agentRepository";

export const AGENT_REPOSITORY_LISTINGS_QUERY_KEY = "agentRepositoryListings";
export const AGENT_REPOSITORY_DETAIL_QUERY_KEY = "agentRepositoryListingDetail";
export const MY_EDITABLE_AGENTS_QUERY_KEY = "myEditableAgents";
export const AGENTS_LIST_QUERY_KEY = "agents";
const IMPORT_PRECHECK_QUERY_KEY = "repositoryImportPrecheck";

export async function invalidateAgentRepositoryCaches(
  queryClient: QueryClient
) {
  const keys = [
    [AGENT_REPOSITORY_LISTINGS_QUERY_KEY],
    [MY_EDITABLE_AGENTS_QUERY_KEY],
    [AGENT_REPOSITORY_DETAIL_QUERY_KEY],
  ] as const;

  await Promise.all(
    keys.map((queryKey) => queryClient.invalidateQueries({ queryKey }))
  );
}

export function useAgentRepositoryListings(
  params?: AgentRepositoryListingListParams,
  enabled = true
) {
  return useQuery({
    queryKey: [AGENT_REPOSITORY_LISTINGS_QUERY_KEY, params],
    queryFn: () => agentRepositoryService.fetchAgentRepositoryListings(params),
    staleTime: 60_000,
    refetchOnMount: "always",
    enabled,
  });
}

export function useMyEditableAgents(
  params?: MyEditableAgentListParams,
  enabled = true
) {
  return useQuery({
    queryKey: [MY_EDITABLE_AGENTS_QUERY_KEY, params],
    queryFn: () => agentRepositoryService.fetchMyEditableAgents(params),
    staleTime: 60_000,
    refetchOnMount: "always",
    enabled,
  });
}

export function useAgentRepositoryListingDetail(
  agentRepositoryId: number | null,
  enabled = true
) {
  return useQuery({
    queryKey: [AGENT_REPOSITORY_DETAIL_QUERY_KEY, agentRepositoryId],
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
      content,
    }: {
      agentRepositoryId: number;
      status: AgentRepositoryListingStatus;
      content?: string;
    }) =>
      agentRepositoryService.updateAgentRepositoryStatus(
        agentRepositoryId,
        status,
        content
      ),
    onSuccess: async () => {
      await invalidateAgentRepositoryCaches(queryClient);
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
    onSuccess: async () => {
      await invalidateAgentRepositoryCaches(queryClient);
    },
  });
}

export function useRepositoryImportPrecheck(
  agentRepositoryId: number | null,
  enabled = true
) {
  return useQuery({
    queryKey: [IMPORT_PRECHECK_QUERY_KEY, agentRepositoryId],
    queryFn: () =>
      agentRepositoryService.fetchRepositoryImportPrecheck(
        agentRepositoryId as number
      ),
    staleTime: 0,
    enabled: enabled && agentRepositoryId != null,
  });
}

export function useImportAgentFromRepository() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (agentRepositoryId: number) =>
      agentRepositoryService.importAgentFromRepository(agentRepositoryId),
    onSuccess: async () => {
      await Promise.all([
        invalidateAgentRepositoryCaches(queryClient),
        queryClient.invalidateQueries({ queryKey: [AGENTS_LIST_QUERY_KEY] }),
      ]);
    },
  });
}
