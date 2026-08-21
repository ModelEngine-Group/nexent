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

export function useOfficialAgents(enabled = true, tenantId?: string) {
  return useQuery({
    queryKey: ["officialAgents", tenantId ?? null],
    queryFn: () => agentRepositoryService.fetchOfficialAgentsWithStatus(tenantId),
    staleTime: 30_000,
    enabled,
  });
}

export function useInstallOfficialAgents(tenantId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: {
      names: string[];
      renames?: Record<string, string>;
      model_ids?: Record<string, number>;
      embedding_model_ids?: Record<string, number>;
      skill_renames?: Record<string, string>;
      kb_renames?: Record<string, string>;
      mcp_renames?: Record<string, string>;
      mcp_skips?: string[];
    }) =>
      agentRepositoryService.installOfficialAgents(
        payload.names,
        {
          renames: payload.renames,
          model_ids: payload.model_ids,
          embedding_model_ids: payload.embedding_model_ids,
          skill_renames: payload.skill_renames,
          kb_renames: payload.kb_renames,
          mcp_renames: payload.mcp_renames,
          mcp_skips: payload.mcp_skips,
        },
        tenantId
      ),
    onSuccess: async () => {
      await Promise.all([
        invalidateAgentRepositoryCaches(queryClient),
        queryClient.invalidateQueries({ queryKey: [AGENTS_LIST_QUERY_KEY] }),
        queryClient.invalidateQueries({ queryKey: ["officialAgents"] }),
      ]);
    },
  });
}

/** Fetch the grouped GitCode AgentsHub catalog (fixed source, no URL input). */
export function useOfficialAgentsFromGitcode(enabled = true, tenantId?: string) {
  return useQuery({
    queryKey: ["officialAgentsGitcode", tenantId ?? null],
    queryFn: () => agentRepositoryService.fetchOfficialAgentsFromGitcode(tenantId),
    staleTime: 30_000,
    enabled,
  });
}

/** Install selected remote official agents by their bundle keys. */
export function useInstallOfficialAgentsFromGitcode(tenantId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: {
      names: string[];
      model_ids?: Record<string, number>;
      embedding_model_ids?: Record<string, number>;
      skill_renames?: Record<string, string>;
      kb_renames?: Record<string, string>;
      mcp_renames?: Record<string, string>;
      mcp_skips?: string[];
    }) =>
      agentRepositoryService.installOfficialAgentsFromGitcode(
        payload.names,
        {
          model_ids: payload.model_ids,
          embedding_model_ids: payload.embedding_model_ids,
          skill_renames: payload.skill_renames,
          kb_renames: payload.kb_renames,
          mcp_renames: payload.mcp_renames,
          mcp_skips: payload.mcp_skips,
        },
        tenantId
      ),
    onSuccess: async () => {
      await Promise.all([
        invalidateAgentRepositoryCaches(queryClient),
        queryClient.invalidateQueries({ queryKey: [AGENTS_LIST_QUERY_KEY] }),
        queryClient.invalidateQueries({ queryKey: ["officialAgents"] }),
        queryClient.invalidateQueries({ queryKey: ["officialAgentsGitcode"] }),
      ]);
    },
  });
}
