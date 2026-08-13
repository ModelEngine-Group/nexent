"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listCommunityMcpReviewTools } from "@/services/mcpToolsService";
import type { CommunityMcpCard, McpTransportFilter } from "@/types/mcpTools";
import { FILTER_ALL, MCP_SEARCH_DEBOUNCE_MS, MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

interface CommunityReviewFilters {
  search: string;
  transport: McpTransportFilter;
  tag: string;
  status: string;
}

const INITIAL_FILTERS: CommunityReviewFilters = {
  search: "",
  transport: FILTER_ALL,
  tag: FILTER_ALL,
  status: FILTER_ALL,
};

export function useMcpCommunityReview(enabled: boolean) {
  const [filters, setFilters] = useState<CommunityReviewFilters>(INITIAL_FILTERS);
  const [debouncedSearch, setDebouncedSearch] = useState(INITIAL_FILTERS.search);
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([null]);
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
  }, [debouncedSearch, filters.transport, filters.tag, filters.status]);

  const query = useQuery({
    queryKey: [
      ...MCP_TOOLS_QUERY_KEYS.communityReview,
      debouncedSearch,
      filters.transport,
      filters.tag,
      filters.status,
      cursorHistory[pageIndex],
    ],
    enabled,
    queryFn: async () => {
      const result = await listCommunityMcpReviewTools({
        search: debouncedSearch || undefined,
        transport_type: filters.transport === FILTER_ALL ? undefined : filters.transport,
        tag: filters.tag === FILTER_ALL ? undefined : filters.tag,
        status: filters.status === FILTER_ALL ? undefined : filters.status,
        cursor: cursorHistory[pageIndex] || undefined,
      });
      return result.data;
    },
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });

  const services: CommunityMcpCard[] = useMemo(
    () => query.data?.items ?? [],
    [query.data?.items]
  );
  const nextCursor = query.data?.nextCursor ?? null;
  const hasPrevPage = pageIndex > 0;
  const hasNextPage = Boolean(nextCursor);

  const nextPage = useCallback(() => {
    if (!nextCursor) return;
    setCursorHistory((prev) => [...prev.slice(0, pageIndex + 1), nextCursor]);
    setPageIndex((prev) => prev + 1);
  }, [nextCursor, pageIndex]);

  const prevPage = useCallback(() => {
    setPageIndex((prev) => Math.max(0, prev - 1));
  }, []);

  const updateFilter = <K extends keyof CommunityReviewFilters>(
    key: K,
    value: CommunityReviewFilters[K]
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
      refetch: query.refetch,
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
      query.refetch,
    ]
  );
}
