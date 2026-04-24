"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchMcpTagStats, listMcpTools } from "@/services/mcpToolsService";
import { filterServiceCards } from "@/lib/mcpTools";
import type { McpServiceItem, McpTagStat } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

export type McpServiceSourceFilter =
  | "all"
  | "local"
  | "mcp_registry"
  | "community";
export type McpServiceTransportFilter = "all" | "http" | "sse" | "container";

export interface McpServicesFilters {
  search: string;
  source: McpServiceSourceFilter;
  transport: McpServiceTransportFilter;
  tag: string;
}

const INITIAL_FILTERS: McpServicesFilters = {
  search: "",
  source: "all",
  transport: "all",
  tag: "all",
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
      const tag = filters.tag === "all" ? undefined : filters.tag;
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
      if (filters.source !== "all" && item.source !== filters.source)
        return false;
      if (
        filters.transport !== "all" &&
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
