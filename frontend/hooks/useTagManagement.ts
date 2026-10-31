// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { tagManagementApi } from "@/services/tagManagementService";
import type {
  TagAssignment,
  TagAssignmentBulkOutcome,
  TagAssignmentBulkReplacePayload,
  TagAssignmentReplacePayload,
  TagDefinition,
  TagLibrary,
  TagResourceType,
} from "@/types/tagManagement";

interface TagQueryState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

interface TagQueryOptions {
  /**
   * Callers that open a tag UI on demand can defer the first read. Defaults to
   * true so existing eager callers keep their behavior.
   */
  enabled?: boolean;
}

function useTagQuery<T>(
  loader: () => Promise<T>,
  enabled = true
): TagQueryState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const refresh = useCallback(async () => {
    // Ignore a stale response after the loader context changed.
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    setError(null);
    try {
      const result = await loader();
      if (requestIdRef.current !== requestId) return;
      setData(result);
    } catch (caught) {
      if (requestIdRef.current !== requestId) return;
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (requestIdRef.current === requestId) setLoading(false);
    }
  }, [loader]);

  useEffect(() => {
    if (!enabled) return;
    void refresh();
  }, [refresh, enabled]);

  return { data, loading, error, refresh };
}

export function useTagLibraries(
  options?: TagQueryOptions
): TagQueryState<TagLibrary[]> {
  return useTagQuery(
    useCallback(() => tagManagementApi.listLibraries(), []),
    options?.enabled ?? true
  );
}

export function useTagDefinitions(
  bucketId: number | null,
  options?: TagQueryOptions
): TagQueryState<TagDefinition[]> {
  const hasBucket = typeof bucketId === "number" && bucketId > 0;
  return useTagQuery(
    useCallback(() => {
      if (!hasBucket || bucketId === null) {
        return Promise.resolve([] as TagDefinition[]);
      }
      return tagManagementApi.listDefinitions(bucketId);
    }, [bucketId, hasBucket]),
    (options?.enabled ?? true) && hasBucket
  );
}

export function useTagAssignments(
  resourceType: string,
  resourceId: string | null,
  options: { provider?: string | null; knowledgeBaseId?: string | null } = {}
): TagQueryState<TagAssignment> & {
  replace: (payload: TagAssignmentReplacePayload) => Promise<TagAssignment>;
  replaceBulk: (
    payload: TagAssignmentBulkReplacePayload
  ) => Promise<TagAssignmentBulkOutcome[]>;
} {
  // Callers routinely inline a fresh { provider, knowledgeBaseId } object on
  // every render.  Memoize by serialized content so the loader (and therefore
  // refresh -> effect) stays stable between renders with equal options, which
  // prevents an infinite "setData -> rerender -> new loader" loop.
  const optionsKey = JSON.stringify(options);
  const stableOptions = useMemo(
    () => options,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [optionsKey]
  );
  const state = useTagQuery(
    useCallback(() => {
      if (resourceId === null) {
        return Promise.resolve({
          resource_type: resourceType as TagResourceType,
          resource_id: "",
          assignment_count: 0,
          assignment_capacity: 100,
          assignments: [],
        } satisfies TagAssignment);
      }
      return tagManagementApi.getAssignments(
        resourceType,
        resourceId,
        stableOptions
      );
    }, [resourceType, resourceId, stableOptions])
  );

  const replace = useCallback(
    async (payload: TagAssignmentReplacePayload) => {
      if (resourceId === null) throw new Error("Resource ID is required");
      const result = await tagManagementApi.replaceAssignments(
        resourceType,
        resourceId,
        payload,
        stableOptions
      );
      await state.refresh();
      return result;
    },
    [resourceType, resourceId, stableOptions, state]
  );

  const replaceBulk = useCallback(
    async (payload: TagAssignmentBulkReplacePayload) => {
      const result = await tagManagementApi.replaceAssignmentsBulk(
        resourceType,
        payload
      );
      await state.refresh();
      return result;
    },
    [resourceType, state]
  );

  return { ...state, replace, replaceBulk };
}
