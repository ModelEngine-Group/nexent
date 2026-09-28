import { useAgentVersionDetail } from "@/hooks/agent/useAgentVersionDetail";
import { useSkillList } from "@/hooks/agent/useSkillList";
import { useToolList } from "@/hooks/agent/useToolList";
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
  const agentId = repositoryDetail?.agent_id ?? null;
  const versionNo = repositoryDetail?.version_no ?? null;
  const versionQuery = useAgentVersionDetail(
    agentId,
    versionNo,
    enabled && repositoryDetail != null
  );
  const versionDetail = versionQuery.agentVersionDetail;
  const { tools } = useToolList({ enabled: enabled && listing != null });
  const { skills } = useSkillList({ enabled: enabled && listing != null });
  const missingVersion =
    repositoryDetail != null && (agentId == null || versionNo == null);

  return {
    repositoryDetail,
    detail: listing
      ? versionDetail && repositoryDetail
        ? mapRepositoryAgentDetail(
            versionDetail,
            repositoryDetail,
            listing.tags,
            {
              tools,
              skills,
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
