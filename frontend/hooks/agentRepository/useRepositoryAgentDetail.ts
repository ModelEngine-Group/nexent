// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useAgentVersionDetail } from "@/hooks/agent/useAgentVersionDetail";
import { useSkillList } from "@/hooks/agent/useSkillList";
import { useToolList } from "@/hooks/agent/useToolList";
import { useModelList } from "@/hooks/model/useModelList";
import { useQueries } from "@tanstack/react-query";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useKnowledgeList } from "@/hooks/knowledge/useKnowledgeList";
import { useResourceTagAssignments } from "@/hooks/useResourceTagAssignments";
import { fetchAgentVersionDetail } from "@/services/agentVersionService";
import { useAgentRepositoryListingDetail } from "@/hooks/agentRepository/useAgentRepositoryListings";
import { mapRepositoryAgentDetail } from "@/lib/myAgentDetail";
import type { AgentRepositoryListingItem } from "@/types/agentRepository";

export function useRepositoryAgentDetail(
  listing: AgentRepositoryListingItem | null,
  enabled: boolean
) {
  const repositoryQuery = useAgentRepositoryListingDetail(
    listing?.agent_repository_id ?? null,
    enabled && listing != null
  );
  const repositoryDetail = repositoryQuery.data;
  const agentId = repositoryDetail?.agent_id ?? listing?.agent_id ?? null;
  const versionNo = repositoryDetail?.version_no ?? listing?.version_no ?? null;
  const versionQuery = useAgentVersionDetail(
    agentId,
    versionNo,
    enabled && listing != null,
    60_000
  );
  const versionDetail = versionQuery.agentVersionDetail;
  const { tools } = useToolList({ enabled: enabled && listing != null });
  const { skills } = useSkillList({ enabled: enabled && listing != null });
  const { models } = useModelList({
    enabled: enabled && Boolean(versionDetail?.model_ids?.length),
  });
  const { user } = useAuthorizationContext();
  const { data: knowledgeBases } = useKnowledgeList(
    enabled && versionDetail?.tools?.length ? (user?.tenantId ?? null) : null
  );
  const subAgentRelations = versionDetail?.sub_agent_relations ?? [];
  const { data: subAgentAssignments } = useResourceTagAssignments(
    "agent",
    enabled,
    subAgentRelations.map((relation) => String(relation.agent_id)),
    0,
    user?.tenantId ?? null
  );
  const subAgentQueries = useQueries({
    queries: (enabled ? subAgentRelations : []).flatMap(
      ({ agent_id, agent_name, version_no }) => {
        if (agent_name || version_no == null) return [];
        return [
          {
            queryKey: ["repositorySubAgent", user?.id, agent_id, version_no],
            queryFn: async () => {
              const result = await fetchAgentVersionDetail(
                agent_id,
                version_no
              );
              return result.success
                ? {
                    id: agent_id,
                    name: result.data.display_name || result.data.name,
                    tags: result.data.tags ?? [],
                  }
                : null;
            },
            staleTime: 60_000,
          },
        ];
      }
    ),
  });
  const subAgents = [
    ...subAgentRelations.flatMap(({ agent_id, agent_name }) =>
      agent_name
        ? [{ id: agent_id, name: agent_name, tags: [] as string[] }]
        : []
    ),
    ...subAgentQueries.flatMap(({ data }) => (data ? [data] : [])),
  ].map(({ id, name, tags }) => ({
    name,
    tags: [
      ...tags,
      ...(subAgentAssignments?.[String(id)] ?? []).map(
        ({ display_value }) => display_value
      ),
    ],
  }));
  const missingVersion =
    repositoryDetail != null && (agentId == null || versionNo == null);

  return {
    repositoryDetail,
    detail: listing
      ? versionDetail && repositoryDetail
        ? mapRepositoryAgentDetail(
            versionDetail,
            {
              ...repositoryDetail,
              published_at:
                repositoryDetail.published_at ?? listing.published_at,
            },
            listing.tags,
            {
              tools,
              skills,
              models,
              knowledgeBases,
              subAgents,
            }
          )
        : undefined
      : null,
    isLoading:
      listing != null &&
      !repositoryQuery.isError &&
      !versionQuery.isError &&
      !missingVersion &&
      (!repositoryDetail || !versionDetail),
    isError: repositoryQuery.isError || versionQuery.isError || missingVersion,
    isFetching: repositoryQuery.isFetching || versionQuery.isFetching,
    retry: () => {
      if (!repositoryDetail || missingVersion) {
        return repositoryQuery.refetch();
      }
      return versionQuery.refetch();
    },
  };
}
