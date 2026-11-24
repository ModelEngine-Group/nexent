// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useCallback,
  useMemo,
  type Dispatch,
  type SetStateAction,
} from "react";
import type { TagResourcePredicate } from "@/types/tagManagement";
import { useRepositoryQueryState } from "./useRepositoryQueryState";

/** Restore validated tag selections without inferring values from tag labels. */
export function useRepositoryTagPredicates(): [
  TagResourcePredicate[],
  Dispatch<SetStateAction<TagResourcePredicate[]>>,
] {
  const [raw, setRaw] = useRepositoryQueryState("tags", "[]");
  const predicates = useMemo(() => {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter(
          (item): item is TagResourcePredicate =>
            !!item &&
            typeof item === "object" &&
            Number.isSafeInteger(item.definition_id) &&
            item.definition_id > 0 &&
            Array.isArray(item.value_ids) &&
            item.value_ids.every(
              (id: unknown) =>
                typeof id === "number" && Number.isSafeInteger(id) && id > 0
            )
        )
        .map((item) => ({
          definition_id: item.definition_id,
          value_ids: item.value_ids,
        }));
    } catch {
      return [];
    }
  }, [raw]);
  const setPredicates = useCallback<
    Dispatch<SetStateAction<TagResourcePredicate[]>>
  >(
    (next) => {
      setRaw(
        JSON.stringify(typeof next === "function" ? next(predicates) : next)
      );
    },
    [predicates, setRaw]
  );
  return [predicates, setPredicates];
}
