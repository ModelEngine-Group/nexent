// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { listUsers } from "@/services/userService";

export function useUserList(
  tenantId: string | null,
  page?: number,
  pageSize?: number,
  filters?: { search?: string; roles?: string[]; groupIds?: number[] }
) {
  const { user } = useAuthorizationContext();
  return useQuery({
    queryKey: ["users", tenantId, page, pageSize, filters, user?.authProvider],
    queryFn: () => listUsers(tenantId, page, pageSize, filters),
    enabled: tenantId !== null,
    staleTime: 1000 * 30,
    refetchOnMount: "always", // Always refetch when component mounts (e.g., when switching tabs)
  });
}
