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
 * Browsing state (search + filters + offset pagination + tag stats) for the
 * community MCP list.
 */
export function useMcpCommunityBrowser(enabled: boolean, pageSize = 30) {
  const [filters, setFilters] = useState<CommunityFilters>(INITIAL_FILTERS);
  const [debouncedSearch, setDebouncedSearch] = useState(
    INITIAL_FILTERS.search
  );
  const [page, setPage] = useState(1);

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedSearch(filters.search),
      MCP_SEARCH_DEBOUNCE_MS
    );
    return () => window.clearTimeout(timer);
  }, [filters.search]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, filters.transport, filters.tag]);

  const query = useQuery({
    queryKey: [
      ...MCP_TOOLS_QUERY_KEYS.communityList,
      debouncedSearch,
      filters.transport,
      filters.tag,
      page,
      pageSize,
    ],
    enabled,
    queryFn: async () => {
      const result = await fetchCommunityMcpCards({
        search: debouncedSearch || undefined,
        transportType:
          filters.transport === FILTER_ALL ? undefined : filters.transport,
        tag: filters.tag === FILTER_ALL ? undefined : filters.tag,
        page,
        limit: pageSize,
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
  const total = query.data?.total ?? 0;
  const tagStats: McpTagStat[] = useMemo(
    () => tagStatsQuery.data ?? [],
    [tagStatsQuery.data]
  );

  useEffect(() => {
    const lastPage = Math.max(1, Math.ceil(total / pageSize));
    if (page > lastPage) setPage(lastPage);
  }, [page, pageSize, total]);

  const hasPrevPage = page > 1;
  const hasNextPage = page * pageSize < total;
  const nextPage = useCallback(() => {
    if (page * pageSize < total) setPage((current) => current + 1);
  }, [page, pageSize, total]);
  const prevPage = useCallback(() => {
    setPage((current) => Math.max(1, current - 1));
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
      page,
      total,
      pageSize,
      setPage,
      hasPrevPage,
      hasNextPage,
      nextPage,
      prevPage,
      refetch: query.refetch,
    }),
    [
      services,
      tagStats,
      query.isLoading,
      query.isFetching,
      filters,
      page,
      total,
      pageSize,
      hasPrevPage,
      hasNextPage,
      nextPage,
      prevPage,
      query.refetch,
    ]
  );
}
