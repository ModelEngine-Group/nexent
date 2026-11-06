// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useResourceTagAssignments } from "@/hooks/useResourceTagAssignments";

/** Read tags once for the visible page; query keys isolate late page responses. */
export function useToolTagAssignments(
  open: boolean,
  toolIds: string[],
  revision: number,
  tenantId: string | null = null
) {
  return useResourceTagAssignments("tool", open, toolIds, revision, tenantId);
}
