"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listMcpTools } from "@/services/mcpToolsService";
import { filterServiceCards } from "@/lib/mcpTools";
import type {
  McpServiceItem,
  McpSourceFilter,
  McpTagStat,
  McpTransportFilter,
} from "@/types/mcpTools";
import { FILTER_ALL } from "@/const/mcpTools";
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
  const [filters, setFilters] = useState<McpServicesFilters>(INITIAL_FILTERS);

  const servicesQuery = useQuery({
    queryKey: [...MCP_TOOLS_QUERY_KEYS.services],
    queryFn: async () => {
      const result = await listMcpTools();
      return result.data;
    },
    staleTime: 30_000,
  });

  const services: McpServiceItem[] = useMemo(
    () => servicesQuery.data ?? [],
    [servicesQuery.data]
  );

  const tagStats: McpTagStat[] = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of services) {
      for (const raw of item.tags || []) {
        const t = String(raw || "").trim();
        if (!t) continue;
        counts.set(t, (counts.get(t) ?? 0) + 1);
      }
    }
    return Array.from(counts.entries())
      .map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => a.tag.localeCompare(b.tag));
  }, [services]);

  const filteredServices = useMemo(() => {
    const keywordFiltered = filterServiceCards(services, filters.search);
    return keywordFiltered.filter((item) => { 
      if (filters.source !== FILTER_ALL && item.source !== filters.source) return false;
      if (filters.transport !== FILTER_ALL && item.transportType !== filters.transport) return false;
      if (filters.tag !== FILTER_ALL && !item.tags.includes(filters.tag)) return false;
      return true;
    });
  }, [services, filters.search, filters.source, filters.transport, filters.tag]);

  const updateFilter = <K extends keyof McpServicesFilters>(
    key: K,
    value: McpServicesFilters[K]
  ) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  return {
    services,
    filteredServices,
    tagStats,
    filters,
    updateFilter,
    loading: servicesQuery.isLoading,
    refetch: servicesQuery.refetch,
  };
}
