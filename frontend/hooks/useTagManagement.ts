import { useCallback, useEffect, useMemo, useState } from "react";

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

function useTagQuery<T>(loader: () => Promise<T>): TagQueryState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await loader();
      setData(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [loader]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}

export function useTagLibraries(): TagQueryState<TagLibrary[]> {
  return useTagQuery(useCallback(() => tagManagementApi.listLibraries(), []));
}

export function useTagDefinitions(
  bucketId: number | null
): TagQueryState<TagDefinition[]> {
  return useTagQuery(
    useCallback(() => {
      if (bucketId === null) return Promise.resolve([] as TagDefinition[]);
      return tagManagementApi.listDefinitions(bucketId);
    }, [bucketId])
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
