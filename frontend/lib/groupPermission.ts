// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { GroupPermission } from "@/types/groupPermission";

export function getGroupPermissions(resource: {
  group_permissions?: GroupPermission[] | null;
  group_ids?: number[] | null;
  ingroup_permission?: string | null;
}): GroupPermission[] {
  if (resource.group_permissions != null) return resource.group_permissions;
  if (resource.ingroup_permission === "PRIVATE") return [];
  const permission =
    resource.ingroup_permission === "EDIT" ? "EDIT" : "READ_ONLY";
  return (resource.group_ids ?? []).map((group_id) => ({
    group_id,
    permission,
  }));
}
