// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

/**
 * Status lookup for the currently selected knowledge resources.
 *
 * The hook is read-only: it never changes the selection, never drops items,
 * and reports a whole-request failure as `lookupFailed` instead of inventing a
 * per-item status. Loading is a separate state so the first render of an
 * unresolved item is never marked as broken.
 */

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  createUnavailableStatus,
  getKnowledgeResourceStatuses,
} from "@/services/knowledgeResourceService";
import type {
  KnowledgeResourceContext,
  KnowledgeResourceProvider,
  KnowledgeResourceStatusEntry,
} from "@/types/knowledgeResource";
import { knowledgeResourceKey } from "@/types/knowledgeResource";

export interface KnowledgeResourceRefInput {
  provider: KnowledgeResourceProvider;
  resourceId: string;
}

export interface KnowledgeResourceStatusesResult {
  /** Status entries keyed by `provider:resource_id`. */
  statusByKey: Record<string, KnowledgeResourceStatusEntry>;
  isLoading: boolean;
  isRefreshing: boolean;
  /** True when the status request failed as a whole for the current selection. */
  lookupFailed: boolean;
  refresh: () => void;
}

export function useKnowledgeResourceStatuses(
  refs: KnowledgeResourceRefInput[],
  context: KnowledgeResourceContext | null,
  enabled: boolean = true
): KnowledgeResourceStatusesResult {
  const requestItems = useMemo(() => {
    const seen = new Map<string, KnowledgeResourceRefInput>();
    refs.forEach((ref) => {
      const resourceId = String(ref.resourceId ?? "").trim();
      if (!resourceId) return;
      seen.set(knowledgeResourceKey(ref.provider, resourceId), {
        provider: ref.provider,
        resourceId,
      });
    });
    return Array.from(seen.entries());
  }, [refs]);

  const queryKey = useMemo(
    () => [
      "knowledge-resource-statuses",
      context,
      requestItems.map(([key]) => key),
    ],
    [context, requestItems]
  );

  const query = useQuery({
    queryKey,
    enabled: enabled && Boolean(context) && requestItems.length > 0,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
    queryFn: async () =>
      getKnowledgeResourceStatuses(
        requestItems.map(([, item]) => ({
          provider: item.provider,
          resource_id: item.resourceId,
        })),
        context as KnowledgeResourceContext
      ),
  });

  const statusByKey = useMemo(() => {
    const result: Record<string, KnowledgeResourceStatusEntry> = {};
    const entries = query.data ?? [];
    const byKey = new Map(
      entries.map((entry) => [
        knowledgeResourceKey(entry.provider, String(entry.resource_id)),
        entry,
      ])
    );
    requestItems.forEach(([key, item]) => {
      const entry = byKey.get(key);
      if (entry) {
        result[key] = { ...entry, resource_id: String(entry.resource_id) };
        return;
      }
      // A requested item without a response is treated as unavailable for the
      // current request; the marker is retryable and the selection is kept.
      if (query.isError) {
        result[key] = createUnavailableStatus(item.provider, item.resourceId);
      }
    });
    return result;
  }, [query.data, query.isError, requestItems]);

  const refresh = useCallback(() => {
    void query.refetch();
  }, [query]);

  return {
    statusByKey,
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    lookupFailed: query.isError,
    refresh,
  };
}
