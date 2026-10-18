// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";
import { tagManagementApi } from "@/services/tagManagementService";

/** One assignment request for the visible canonical resource IDs. */
export function useResourceTagAssignments(
  resourceType: "tool" | "agent",
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
      const results = await (resourceType === "tool"
        ? tagManagementApi.getToolAssignmentsBatch(resourceIds)
        : tagManagementApi.getAgentAssignmentsBatch(resourceIds));
      return Object.fromEntries(
        results.map((result) => [result.resource_id, result.assignments])
      );
    },
  });
}
