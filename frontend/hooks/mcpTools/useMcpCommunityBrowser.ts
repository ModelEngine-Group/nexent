"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchCommunityMcpCards,
  fetchCommunityMcpTagStats,
} from "@/services/mcpToolsService";
import type {
  CommunityMcpCard,
  McpTagStat,
  McpTransportFilter,
} from "@/types/mcpTools";
import { FILTER_ALL } from "@/const/mcpTools";
import { MCP_SEARCH_DEBOUNCE_MS, MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

export type CommunityTransportFilter = McpTransportFilter;

interface CommunityFilters {
  search: string;
  transport: McpTransportFilter;
  tag: string;
}

const INITIAL_FILTERS: CommunityFilters = {
  search: "",
  transport: FILTER_ALL,
  tag: FILTER_ALL,
};

/**
 * Browsing state (search + filters + cursor pagination + tag stats) for the
 * community MCP list.
 */
export function useMcpCommunityBrowser(enabled: boolean) {
  const [filters, setFilters] = useState<CommunityFilters>(INITIAL_FILTERS);
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
  }, [debouncedSearch, filters.transport, filters.tag]);

  const query = useQuery({
    queryKey: [
      ...MCP_TOOLS_QUERY_KEYS.communityList,
      debouncedSearch,
      filters.transport,
      filters.tag,
      cursorHistory[pageIndex],
    ],
    enabled,
    queryFn: async () => {
      const result = await fetchCommunityMcpCards({
        search: debouncedSearch || undefined,
        transportType: filters.transport === FILTER_ALL ? undefined : filters.transport,
        tag: filters.tag === FILTER_ALL ? undefined : filters.tag,
        cursor: cursorHistory[pageIndex],
      });
      return result.data;
    },
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });

  const tagStatsQuery = useQuery({
    queryKey: [...MCP_TOOLS_QUERY_KEYS.communityTags],
    enabled,
    queryFn: async () => {
      const result = await fetchCommunityMcpTagStats();
      return result.data;
    },
    staleTime: 60_000,
  });

  const services: CommunityMcpCard[] = useMemo(
    () => query.data?.items ?? [],
    [query.data?.items]
  );
  const nextCursor = query.data?.nextCursor ?? null;
  const tagStats: McpTagStat[] = useMemo(
    () => tagStatsQuery.data ?? [],
    [tagStatsQuery.data]
  );

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

  const updateFilter = <K extends keyof CommunityFilters>(
    key: K,
    value: CommunityFilters[K]
  ) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  return useMemo(
    () => ({
      services,
      tagStats,
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
      tagStats,
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
