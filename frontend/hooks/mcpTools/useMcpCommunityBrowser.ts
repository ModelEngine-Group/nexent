// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { useRepositoryQueryState } from "@/hooks/useRepositoryQueryState";
import {
  fetchCommunityMcpCards,
  fetchCommunityMcpTagStats,
} from "@/services/mcpToolsService";
import type {
  CommunityMcpCard,
  McpTagStat,
  McpTransportFilter,
} from "@/types/mcpTools";
import { FILTER_ALL, McpTransportType } from "@/const/mcpTools";
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
export function useMcpCommunityBrowser(
  enabled: boolean,
  pageSize = 30,
  sortByPublished = false
) {
  const presentation = useRepositoryPresentation();
  const [search, setSearch] = useRepositoryQueryState("search", "");
  const [transport, setTransport] = useRepositoryQueryState<McpTransportFilter>(
    "transport",
    FILTER_ALL,
    [FILTER_ALL, ...Object.values(McpTransportType)]
  );
  const [tag, setTag] = useRepositoryQueryState("tag", FILTER_ALL);
  const filters = useMemo(
    () => ({ search, transport, tag }),
    [search, transport, tag]
  );
  const [debouncedSearch, setDebouncedSearch] = useState(
    INITIAL_FILTERS.search
  );
  const [page, setPage] = useRepositoryQueryState("page", 1);

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedSearch(filters.search),
      MCP_SEARCH_DEBOUNCE_MS
    );
    return () => window.clearTimeout(timer);
  }, [filters.search]);

  useEffect(() => {
    if (!presentation) setPage(1);
  }, [
    debouncedSearch,
    filters.transport,
    filters.tag,
    sortByPublished,
    presentation,
    setPage,
  ]);

  const queryScope = [
    ...MCP_TOOLS_QUERY_KEYS.communityList,
    debouncedSearch,
    filters.transport,
    filters.tag,
    pageSize,
    sortByPublished,
  ];
  const query = useQuery({
    queryKey: [...queryScope, page],
    placeholderData: presentation
      ? (previousData, previousQuery) =>
          queryScope.every(
            (value, index) => previousQuery?.queryKey[index] === value
          )
            ? previousData
            : undefined
      : undefined,
    enabled,
    queryFn: async () => {
      const result = await fetchCommunityMcpCards({
        search: debouncedSearch || undefined,
        transportType:
          filters.transport === FILTER_ALL ? undefined : filters.transport,
        tag: filters.tag === FILTER_ALL ? undefined : filters.tag,
        page,
        ...(sortByPublished ? { sort_by_published_time: true } : {}),
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
    if (query.data === undefined || query.isPlaceholderData) return;
    const lastPage = Math.max(1, Math.ceil(total / pageSize));
    if (page > lastPage) setPage(lastPage);
  }, [page, pageSize, query.data, query.isPlaceholderData, total, setPage]);

  const hasPrevPage = page > 1;
  const hasNextPage = page * pageSize < total;
  const nextPage = useCallback(() => {
    if (page * pageSize < total) setPage((current) => current + 1);
  }, [page, pageSize, total, setPage]);
  const prevPage = useCallback(() => {
    setPage((current) => Math.max(1, current - 1));
  }, [setPage]);

  const updateFilter = useCallback(
    <K extends keyof CommunityFilters>(key: K, value: CommunityFilters[K]) => {
      if (key === "search") setSearch(String(value));
      else if (key === "transport") setTransport(value as McpTransportFilter);
      else setTag(String(value));
      if (presentation) setPage(1);
    },
    [presentation, setSearch, setTransport, setTag, setPage]
  );

  const loading = query.isLoading || (!presentation && query.isFetching);
  return useMemo(
    () => ({
      services,
      tagStats,
      loading,
      error: query.error,
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
      loading,
      query.error,
      filters,
      page,
      total,
      pageSize,
      hasPrevPage,
      hasNextPage,
      nextPage,
      prevPage,
      query.refetch,
      setPage,
      updateFilter,
    ]
  );
}
