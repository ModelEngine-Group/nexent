// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { loadTenantMemorySettings } from "@/services/memoryService";

export function tenantMemorySettingsKey(
  tenantId: string | undefined,
  userId: string | undefined
) {
  return ["tenant-memory-settings", tenantId, userId] as const;
}

export function useTenantMemorySettings() {
  const { user } = useAuthorizationContext();

  return useQuery({
    queryKey: tenantMemorySettingsKey(user?.tenantId, user?.id),
    queryFn: loadTenantMemorySettings,
    enabled: Boolean(user?.tenantId && user?.id),
  });
}
