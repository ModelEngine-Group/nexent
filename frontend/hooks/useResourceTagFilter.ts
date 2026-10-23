// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { tagManagementApi } from "@/services/tagManagementService";
import type {
  TagResourcePredicate,
  TagResourceType,
} from "@/types/tagManagement";

/** Match only the caller's authorized candidates; selection remains caller-owned. */
export function useResourceTagFilter(
  open: boolean,
  resourceType: TagResourceType,
  candidateIds: string[]
) {
  const { t } = useTranslation("common");
  const [predicates, setPredicates] = useState<TagResourcePredicate[]>([]);
  const [revision, setRevision] = useState(0);
  const candidateKey = JSON.stringify([...new Set(candidateIds)]);
  const candidates = useMemo<string[]>(
    () => JSON.parse(candidateKey),
    [candidateKey]
  );
  const [previousOpen, setPreviousOpen] = useState(open);
  if (previousOpen !== open) {
    setPreviousOpen(open);
    if (!open) setPredicates([]);
  }

  const definitions = useQuery({
    queryKey: ["resourceTagDefinitions", resourceType, revision],
    enabled: open,
    staleTime: 30000,
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
    queryKey: [
      "resourceTagMatches",
      resourceType,
      candidates,
      predicates,
      revision,
    ],
    enabled: open && predicates.length > 0,
    queryFn: async () => {
      const responses = await Promise.all(
        Array.from({ length: Math.ceil(candidates.length / 500) }, (_, index) =>
          tagManagementApi.filterResourceIds(
            resourceType,
            candidates.slice(index * 500, (index + 1) * 500),
            predicates
          )
        )
      );
      const allowed = new Set(candidates);
      return new Set(
        responses
          .flatMap((response) => response.matched_resource_ids)
          .filter((id) => allowed.has(id))
      );
    },
  });
  const emptyIds = useMemo(() => new Set<string>(), []);
  const matchedIds = predicates.length
    ? matches.isError
      ? emptyIds
      : (matches.data ?? emptyIds)
    : null;
  const error = definitions.isError
    ? t("workbench.controls.tagsLoadFailed", "标签加载失败，请重试")
    : predicates.length && matches.isError
      ? t(
          "workbench.controls.tagsFilterFailed",
          "标签筛选失败，请重试或清除筛选"
        )
      : undefined;
  return {
    definitions: definitions.data ?? [],
    predicates,
    setPredicates,
    matchedIds,
    filtering: predicates.length > 0 && matches.isFetching,
    loading: definitions.isFetching,
    error,
    revision,
    retry: () => setRevision((value) => value + 1),
  };
}
