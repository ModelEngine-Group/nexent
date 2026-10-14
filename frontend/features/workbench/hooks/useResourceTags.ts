import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { tagManagementApi } from "@/services/tagManagementService";
import type {
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
  candidateIds: string[],
  filterOnServer = false
) {
  const { t } = useTranslation();
  const [predicates, setPredicates] = useState<TagResourcePredicate[]>([]);
  const [previousOpen, setPreviousOpen] = useState(open);
  if (previousOpen !== open) {
    setPreviousOpen(open);
    if (!open) setPredicates([]);
  }
  const definitions = useQuery({
    queryKey: ["workbenchTagDefinitions", resourceType],
    enabled: open,
    queryFn: async () => {
      const libraries = await tagManagementApi.listLibraries();
      const groups = await Promise.all(
        libraries
          .filter(
            (library) =>
              library.status === "active" &&
              library.resource_types.includes(resourceType)
          )
          .map((library) => tagManagementApi.listDefinitions(library.bucket_id))
      );
      return groups
        .flat()
        .filter((definition) => definition.status === "active");
    },
  });
  const matches = useQuery({
    queryKey: ["workbenchTagMatches", resourceType, candidateIds, predicates],
    enabled: open && !filterOnServer && predicates.length > 0,
    queryFn: async () => {
      const candidates = Array.from(new Set(candidateIds));
      const results = await Promise.all(
        Array.from({ length: Math.ceil(candidates.length / 500) }, (_, index) =>
          tagManagementApi.filterResourceIds(
            resourceType,
            candidates.slice(index * 500, (index + 1) * 500),
            predicates
          )
        )
      );
      return intersectAuthorizedIds(
        candidates,
        results.flatMap((result) => result.matched_resource_ids)
      );
    },
  });
  return {
    definitions: definitions.data ?? [],
    predicates,
    setPredicates,
    loading:
      definitions.isFetching ||
      (!filterOnServer && predicates.length > 0 && matches.isFetching),
    error: definitions.isError
      ? t("workbench.controls.tagsLoadFailed", "标签加载失败，请重试")
      : matches.isError && predicates.length > 0 && !filterOnServer
        ? t(
            "workbench.controls.tagsFilterFailed",
            "标签筛选失败，请重试或清除筛选"
          )
        : undefined,
    retry: () => {
      void definitions.refetch();
      if (predicates.length && !filterOnServer) void matches.refetch();
    },
    visibleIds:
      predicates.length && !filterOnServer
        ? matches.isError
          ? new Set<string>()
          : (matches.data ?? new Set<string>())
        : null,
  };
}
