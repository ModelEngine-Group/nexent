"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRegistryMcpCards } from "@/services/mcpToolsService";
import type { RegistryMcpCard } from "@/types/mcpTools";
import { MCP_SEARCH_DEBOUNCE_MS, MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

interface RegistryFilters {
  search: string;
  version: string;
  updatedSince: string;
  includeDeleted: boolean;
}

const INITIAL_FILTERS: RegistryFilters = {
  search: "",
  version: "latest",
  updatedSince: "",
  includeDeleted: false,
};

/**
 * Browsing state (search + filters + cursor pagination) for the MCP registry.
 * The caller renders whatever list/card UI it likes; this hook only maintains
 * the fetch and pagination.
 */
export function useMcpRegistryBrowser(enabled: boolean) {
  const [filters, setFilters] = useState<RegistryFilters>(INITIAL_FILTERS);
  const [debouncedSearch, setDebouncedSearch] = useState(
    INITIAL_FILTERS.search
  );
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([
    null,
  ]);
  const [pageIndex, setPageIndex] = useState(0);

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedSearch(filters.search),
      MCP_SEARCH_DEBOUNCE_MS
    );
    return () => window.clearTimeout(timer);
  }, [filters.search]);

  useEffect(() => {
    setCursorHistory([null]);
    setPageIndex(0);
  }, [
    debouncedSearch,
    filters.version,
    filters.updatedSince,
    filters.includeDeleted,
  ]);

  const query = useQuery({
    queryKey: [
      ...MCP_TOOLS_QUERY_KEYS.registryList,
      debouncedSearch,
      filters.version,
      filters.updatedSince,
      filters.includeDeleted,
      cursorHistory[pageIndex],
    ],
    enabled,
    queryFn: async () => {
      const result = await fetchRegistryMcpCards({
        search: debouncedSearch || undefined,
        version: filters.version || undefined,
        updatedSince: filters.updatedSince || undefined,
        includeDeleted: filters.includeDeleted,
        cursor: cursorHistory[pageIndex],
      });
      return result.data;
    },
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });

  const services: RegistryMcpCard[] = useMemo(
    () => query.data?.items ?? [],
    [query.data?.items]
  );
  const nextCursor = query.data?.nextCursor ?? null;

  const hasPrevPage = pageIndex > 0;
  const hasNextPage = Boolean(nextCursor);

  const nextPage = useCallback(() => {
    if (!nextCursor) return;
    setCursorHistory((prev) => {
      const truncated = prev.slice(0, pageIndex + 1);
      return [...truncated, nextCursor];
    });
    setPageIndex((prev) => prev + 1);
  }, [nextCursor, pageIndex]);

  const prevPage = useCallback(() => {
    setPageIndex((prev) => Math.max(0, prev - 1));
  }, []);

  const updateFilter = <K extends keyof RegistryFilters>(
    key: K,
    value: RegistryFilters[K]
  ) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  return useMemo(
    () => ({
      services,
      loading: query.isLoading || query.isFetching,
      filters,
      updateFilter,
      page: pageIndex + 1,
      hasPrevPage,
      hasNextPage,
      nextPage,
      prevPage,
    }),
    [
      services,
      query.isLoading,
      query.isFetching,
      filters,
      pageIndex,
      hasPrevPage,
      hasNextPage,
      nextPage,
      prevPage,
    ]
  );
}
