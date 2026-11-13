// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useAgentVersionDetail } from "@/hooks/agent/useAgentVersionDetail";
import { useSkillList } from "@/hooks/agent/useSkillList";
import { useToolList } from "@/hooks/agent/useToolList";
import { useAgentRepositoryListingDetail } from "@/hooks/agentRepository/useAgentRepositoryListings";
import {
  mapOfficialRepositoryDetail,
  mapRepositoryAgentDetail,
} from "@/lib/myAgentDetail";
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
    enabled && repositoryDetail != null && repositoryDetail.is_official !== true
  );
  const versionDetail = versionQuery.agentVersionDetail;
  const { tools } = useToolList({ enabled: enabled && listing != null });
  const { skills } = useSkillList({ enabled: enabled && listing != null });
  const missingVersion =
    repositoryDetail?.is_official !== true &&
    repositoryDetail != null &&
    (agentId == null || versionNo == null);
  const detail =
    listing && repositoryDetail?.is_official === true
      ? mapOfficialRepositoryDetail(repositoryDetail, listing.tags)
      : listing && versionDetail && repositoryDetail
        ? mapRepositoryAgentDetail(
            versionDetail,
            repositoryDetail,
            listing.tags,
            {
              tools,
              skills,
            }
          )
        : listing
          ? undefined
          : null;

  return {
    repositoryDetail,
    detail,
    isLoading:
      listing != null &&
      !repositoryQuery.isError &&
      !versionQuery.isError &&
      !missingVersion &&
      (!repositoryDetail ||
        (repositoryDetail.is_official !== true && !versionDetail)),
    isError: repositoryQuery.isError || versionQuery.isError || missingVersion,
    isFetching: repositoryQuery.isFetching || versionQuery.isFetching,
    retry: () => {
      if (!repositoryDetail || missingVersion || repositoryDetail.is_official) {
        return repositoryQuery.refetch();
      }
      return versionQuery.refetch();
    },
  };
}
