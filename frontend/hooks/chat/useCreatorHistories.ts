// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useMemo } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
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
  const query = useInfiniteQuery({
    queryKey,
    enabled: Boolean(user?.id && user?.tenantId && targetId && targetId > 0),
    initialPageParam: 0,
    staleTime: 30_000,
    queryFn: ({ pageParam }) =>
      conversationService.getCreatorHistories(kind, targetId!, pageParam),
    getNextPageParam: (last, pages) => {
      const count = pages.reduce((sum, page) => sum + page.items.length, 0);
      return last.items.length && count < last.total ? count : undefined;
    },
  });
  return {
    items: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: targetId && targetId > 0 ? query.data?.pages[0]?.total : 0,
    pending: query.isLoading,
    failed: query.isError,
    fetchingMore: query.isFetchingNextPage,
    hasMore: query.hasNextPage,
    loadMore: () => query.fetchNextPage(),
    refetch: () =>
      targetId && targetId > 0 ? query.refetch() : Promise.resolve(undefined),
    refresh,
  };
}
