// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";

/** Resolve installed state consistently for repository cards and details. */
export function isCommunityMcpInstalled(
  service: Pick<CommunityMcpCard, "communityId" | "name">,
  localServices: readonly Pick<
    McpServiceItem,
    "communityId" | "name" | "permission"
  >[],
): boolean {
  return localServices.some((local) => {
    if (local.permission !== "EDIT") return false;
    if (service.communityId != null && local.communityId != null) {
      return local.communityId === service.communityId;
    }
    // Legacy records may not carry a source ID yet.
    return local.name === service.name;
  });
}
