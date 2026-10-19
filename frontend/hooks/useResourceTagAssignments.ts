// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";
import { tagManagementApi } from "@/services/tagManagementService";

/** One assignment request for the visible canonical resource IDs. */
export function useResourceTagAssignments(
  resourceType: "tool" | "agent" | "skill" | "knowledge_base",
  open: boolean,
  resourceIds: string[],
  revision: number,
  tenantId: string | null = null
) {
  return useQuery({
    queryKey: [
      "resourceTagAssignments",
      resourceType,
      tenantId,
      resourceIds,
      revision,
    ],
    enabled: open && resourceIds.length > 0,
    staleTime: 0,
    retry: false,
    queryFn: async () => {
      const loaders = {
        tool: tagManagementApi.getToolAssignmentsBatch,
        agent: tagManagementApi.getAgentAssignmentsBatch,
        skill: tagManagementApi.getSkillAssignmentsBatch,
        knowledge_base: tagManagementApi.getKnowledgeAssignmentsBatch,
      };
      const results = await loaders[resourceType](resourceIds);
      return Object.fromEntries(
        results.map((result) => [result.resource_id, result.assignments])
      );
    },
  });
}
