"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchMcpTagStats, listMcpTools } from "@/services/mcpToolsService";
import { filterServiceCards } from "@/lib/mcpTools";
import type {
  McpServiceItem,
  McpSourceFilter,
  McpTagStat,
  McpTransportFilter,
} from "@/types/mcpTools";
import { FILTER_ALL } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

export type McpServiceSourceFilter = McpSourceFilter;
export type McpServiceTransportFilter = McpTransportFilter;

export interface McpServicesFilters {
  search: string;
  source: McpSourceFilter;
  transport: McpTransportFilter;
  tag: string;
}

const INITIAL_FILTERS: McpServicesFilters = {
  search: "",
  source: FILTER_ALL,
  transport: FILTER_ALL,
  tag: FILTER_ALL,
};

/**
 * Owns the cached list of MCP services + filter state. Keeps the page free of
 * fetch / derive / filter plumbing.
 */
export function useMcpServicesList() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<McpServicesFilters>(INITIAL_FILTERS);

  const servicesQuery = useQuery({
    queryKey: [...MCP_TOOLS_QUERY_KEYS.services, filters.tag],
    queryFn: async () => {
      const tag = filters.tag === FILTER_ALL ? undefined : filters.tag;
      const result = await listMcpTools(tag ? { tag } : undefined);
      return result.data;
    },
    staleTime: 30_000,
  });

  const tagStatsQuery = useQuery({
    queryKey: [...MCP_TOOLS_QUERY_KEYS.tagStats],
    queryFn: async () => {
      const result = await fetchMcpTagStats();
      return result.data;
    },
    staleTime: 60_000,
  });

  const services: McpServiceItem[] = useMemo(
    () => servicesQuery.data ?? [],
    [servicesQuery.data]
  );
  const tagStats: McpTagStat[] = useMemo(
    () => tagStatsQuery.data ?? [],
    [tagStatsQuery.data]
  );

  const filteredServices = useMemo(() => {
    const keywordFiltered = filterServiceCards(services, filters.search);
    return keywordFiltered.filter((item) => {
      if (filters.source !== FILTER_ALL && item.source !== filters.source)
        return false;
      if (
        filters.transport !== FILTER_ALL &&
        item.transportType !== filters.transport
      )
        return false;
      return true;
    });
  }, [services, filters.search, filters.source, filters.transport]);

  const updateFilter = <K extends keyof McpServicesFilters>(
    key: K,
    value: McpServicesFilters[K]
  ) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["mcp-tools"] });

  return {
    services,
    filteredServices,
    tagStats,
    filters,
    updateFilter,
    loading: servicesQuery.isLoading,
    refresh,
  };
}
