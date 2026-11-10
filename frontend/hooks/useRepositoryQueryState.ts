// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useCallback,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useRepositoryPresentation } from "./useRepositoryPresentation";

const repositoryPageSizes = ["10", "12", "20", "50", "100"] as const;

export function useRepositoryPageSize() {
  const presentation = useRepositoryPresentation();
  const [size, setSize] = useRepositoryQueryState(
    "page_size",
    presentation?.layout === "list" ? "10" : "12",
    repositoryPageSizes
  );
  const onChange = (nextSize: number) => {
    const option = repositoryPageSizes.find(
      (value) => Number(value) === nextSize
    );
    if (option) setSize(option);
  };
  return [Number(size), onChange] as const;
}

/** Legacy pages keep local state; the unified page restores state from its URL. */
export function useRepositoryQueryState(
  key: string,
  initial: string
): [string, Dispatch<SetStateAction<string>>];
export function useRepositoryQueryState(
  key: string,
  initial: number
): [number, Dispatch<SetStateAction<number>>];
export function useRepositoryQueryState<T extends string>(
  key: string,
  initial: T,
  allowed: readonly T[]
): [T, Dispatch<SetStateAction<T>>];
export function useRepositoryQueryState<T extends string | number>(
  key: string,
  initial: T,
  allowed?: readonly T[]
): [T, Dispatch<SetStateAction<T>>] {
  const presentation = useRepositoryPresentation();
  const [local, setLocal] = useState(initial);
  const raw = presentation?.query?.get(key);
  let value = local;
  if (presentation?.query) {
    value = (
      typeof initial === "number"
        ? raw && Number.isSafeInteger(Number(raw)) && Number(raw) > 0
          ? Number(raw)
          : initial
        : (raw ?? initial)
    ) as T;
  }
  if (allowed && !allowed.includes(value)) value = initial;
  const updateQuery = presentation?.updateQuery;
  const setValue = useCallback<Dispatch<SetStateAction<T>>>(
    (next) => {
      if (!updateQuery) {
        setLocal(next);
        return;
      }
      const resolved =
        typeof next === "function" ? (next as (previous: T) => T)(value) : next;
      updateQuery(
        {
          [key]: key === "search" && resolved === "" ? null : String(resolved),
          ...(key !== "page" ? { page: "1" } : {}),
        },
        key === "search"
      );
    },
    [key, value, updateQuery]
  );
  return [value, updateQuery ? setValue : setLocal];
}
