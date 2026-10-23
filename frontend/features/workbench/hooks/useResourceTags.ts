import { useEffect, useState } from "react";
import { tagManagementApi } from "@/services/tagManagementService";
import type {
  TagDefinition,
  TagResourcePredicate,
  TagResourceType,
} from "@/types/tagManagement";

/** Tag responses may narrow authorized candidates, never expand them. */
export function intersectAuthorizedIds(
  candidates: readonly string[],
  matched: readonly string[]
) {
  const allowed = new Set(candidates);
  return new Set(matched.filter((id) => allowed.has(id)));
}

export function useResourceTags(
  open: boolean,
  resourceType: TagResourceType,
  candidateIds: string[]
) {
  const [definitions, setDefinitions] = useState<TagDefinition[]>([]);
  const [predicates, setPredicates] = useState<TagResourcePredicate[]>([]);
  const [visibleIds, setVisibleIds] = useState<Set<string> | null>(null);
  const [error, setError] = useState<string>();
  const candidateKey = JSON.stringify(candidateIds);
  const [resolvedKey, setResolvedKey] = useState("");
  const requestKey = JSON.stringify([candidateKey, predicates]);
  useEffect(() => {
    if (!open) {
      setPredicates([]);
      return;
    }
    let cancelled = false;
    void tagManagementApi
      .listLibraries()
      .then(async (libraries) => {
        const librariesForType = libraries.filter(
          (library) =>
            library.status === "active" &&
            library.resource_types.includes(resourceType)
        );
        const groups = await Promise.all(
          librariesForType.map((library) =>
            tagManagementApi.listDefinitions(library.bucket_id)
          )
        );
        if (!cancelled) setDefinitions(groups.flat());
      })
      .catch(() => {
        if (!cancelled) setError("标签定义加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [open, resourceType]);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setError(undefined);
    if (!predicates.length) {
      setVisibleIds(null);
      setResolvedKey(requestKey);
      return;
    }
    const candidates: string[] = JSON.parse(candidateKey);
    void tagManagementApi
      .filterResourceIds(resourceType, candidates, predicates)
      .then((result) => {
        if (!cancelled) {
          setVisibleIds(
            intersectAuthorizedIds(candidates, result.matched_resource_ids)
          );
          setResolvedKey(requestKey);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setVisibleIds(new Set());
          setResolvedKey(requestKey);
          setError("标签筛选失败，请重试或清除筛选");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, candidateKey, predicates, resourceType, requestKey]);
  return {
    definitions,
    predicates,
    setPredicates,
    error,
    visibleIds:
      predicates.length && resolvedKey !== requestKey
        ? new Set<string>()
        : visibleIds,
  };
}
