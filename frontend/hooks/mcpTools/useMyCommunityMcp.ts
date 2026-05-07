"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listMyCommunityMcpTools } from "@/services/mcpToolsService";
import type {
  CommunityMcpCard,
  McpTagStat,
  McpTransportFilter,
} from "@/types/mcpTools";
import { FILTER_ALL, MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

export interface MyCommunityMcpFilters {
  search: string;
  transport: McpTransportFilter;
  tag: string;
}

const INITIAL_FILTERS: MyCommunityMcpFilters = {
  search: "",
  transport: FILTER_ALL,
  tag: FILTER_ALL,
};

/**
 * Published tab: loads and filters "my community MCP" list. Edit/save/delete for
 * a single row lives in {@link usePublishedServiceDetailEdit} inside the detail modal.
 */
export function useMyCommunityMcp(enabled: boolean) {
  const [filters, setFilters] = useState<MyCommunityMcpFilters>(INITIAL_FILTERS);

  const query = useQuery({
    queryKey: [...MCP_TOOLS_QUERY_KEYS.myCommunity],
    enabled,
    queryFn: async () => {
      const result = await listMyCommunityMcpTools();
      return result.data.items;
    },
    staleTime: 30_000,
  });

  const items: CommunityMcpCard[] = useMemo(
    () => query.data ?? [],
    [query.data]
  );

  const tagStats: McpTagStat[] = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of items) {
      for (const raw of item.tags || []) {
        const t = String(raw || "").trim();
        if (!t) continue;
        counts.set(t, (counts.get(t) ?? 0) + 1);
      }
    }
    return Array.from(counts.entries())
      .map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => a.tag.localeCompare(b.tag));
  }, [items]);

  const filteredItems = useMemo(() => {
    const keyword = filters.search.trim().toLowerCase();
    return items.filter((item) => {
      if (keyword) {
        const tags = (item.tags || []).join(",").toLowerCase();
        const hit =
          (item.name || "").toLowerCase().includes(keyword) ||
          (item.description || "").toLowerCase().includes(keyword) ||
          tags.includes(keyword);
        if (!hit) return false;
      }
      if (
        filters.transport !== FILTER_ALL &&
        item.transportType !== filters.transport
      ) {
        return false;
      }
      if (
        filters.tag !== FILTER_ALL &&
        !(item.tags || []).includes(filters.tag)
      ) {
        return false;
      }
      return true;
    });
  }, [items, filters.search, filters.transport, filters.tag]);

  const updateFilter = <K extends keyof MyCommunityMcpFilters>(
    key: K,
    value: MyCommunityMcpFilters[K]
  ) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  return {
    loading: query.isLoading,
    items,
    filteredItems,
    tagStats,
    filters,
    updateFilter,
    search: filters.search,
    setSearch: (value: string) => updateFilter("search", value),
  };
}
