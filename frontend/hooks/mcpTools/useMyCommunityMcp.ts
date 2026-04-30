"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listMyCommunityMcpTools } from "@/services/mcpToolsService";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

/**
 * Published tab: loads and filters "my community MCP" list. Edit/save/delete for
 * a single row lives in {@link usePublishedServiceDetailEdit} inside the detail modal.
 */
export function useMyCommunityMcp(enabled: boolean) {
  const [search, setSearch] = useState("");

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

  const filteredItems = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return items;
    return items.filter((item) => {
      const tags = (item.tags || []).join(",").toLowerCase();
      return (
        (item.name || "").toLowerCase().includes(keyword) ||
        (item.description || "").toLowerCase().includes(keyword) ||
        tags.includes(keyword)
      );
    });
  }, [items, search]);

  return {
    loading: query.isLoading,
    items,
    filteredItems,
    search,
    setSearch,
  };
}
