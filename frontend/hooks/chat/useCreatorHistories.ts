// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { conversationService } from "@/services/conversationService";
import type { ConversationTarget } from "@/types/conversation";

export function useCreatorHistories(
  kind: ConversationTarget["type"],
  targetId: number | null
) {
  const { user } = useAuthorizationContext();
  const client = useQueryClient();
  const queryKey = useMemo(
    () => ["creator-histories", user?.id, user?.tenantId, kind, targetId],
    [user?.id, user?.tenantId, kind, targetId]
  );
  const refresh = useCallback(
    () => client.invalidateQueries({ queryKey, exact: true }),
    [client, queryKey]
  );
  const query = useQuery({
    queryKey,
    enabled: Boolean(user?.id && user?.tenantId && targetId && targetId > 0),
    staleTime: 30_000,
    queryFn: () => conversationService.getCreatorHistories(kind, targetId!),
  });
  return {
    items: query.data?.items.slice(0, 3) ?? [],
    total:
      targetId && targetId > 0
        ? query.data
          ? Math.min(query.data.total, 3)
          : undefined
        : 0,
    pending: query.isLoading,
    ready: query.isSuccess,
    failed: query.isError,
    refetch: () =>
      targetId && targetId > 0 ? query.refetch() : Promise.resolve(undefined),
    refresh,
  };
}
