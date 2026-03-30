import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import log from "@/lib/logger";
import { filterServiceCards } from "@/lib/mcpTools";
import type { McpTool } from "@/types/agentConfig";
import type { McpServiceItem } from "@/types/mcpTools";
import { listMcpTools } from "@/services/mcpToolsService";
import { useMcpToolsDetail } from "./useMcpToolsDetail";
import { useMcpToolsToggle } from "./useMcpToolsToggle";

type UseMcpToolsPageParams = {
  t: (key: string) => string;
  message: MessageInstance;
};

function isSameToolNames(left: string[] = [], right: string[] = []) {
  if (left.length !== right.length) return false;
  return left.every((item, index) => item === right[index]);
}

export function useMcpToolsPage({ t, message }: UseMcpToolsPageParams) {
  const [searchValue, setSearchValue] = useState("");
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [transportTypeFilter, setTransportTypeFilter] = useState<string>("all");
  const [services, setServices] = useState<McpServiceItem[]>([]);
  const [selectedService, setSelectedService] = useState<McpServiceItem | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);

  const listQuery = useQuery<McpServiceItem[]>({
    queryKey: ["mcp-tools", "list"],
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: async () => {
      const result = await listMcpTools();
      return result.data;
    },
  });

  useEffect(() => {
    if (!listQuery.data) return;
    setServices(listQuery.data);
  }, [listQuery.data]);

  useEffect(() => {
    if (!(listQuery.error instanceof Error)) return;
    log.error("[useMcpToolsPage] Failed to load managed MCP service list", { error: listQuery.error });
    message.error(t("mcpTools.list.loadFailed"));
  }, [listQuery.error, message, t]);

  const loadServerList = useCallback(async () => {
    const result = await listQuery.refetch();
    if (result.error || !result.data) {
      log.error("[useMcpToolsPage] Failed to refresh managed MCP service list", { error: result.error });
      message.error(t("mcpTools.list.loadFailed"));
      return { success: false, data: undefined };
    }

    setServices(result.data);
    return { success: true, data: result.data };
  }, [listQuery, message, t]);

  const filteredServices = useMemo(() => {
    const searched = filterServiceCards(services, searchValue);
    return searched.filter((item) => {
      const sourceMatched = sourceFilter === "all" || item.source === sourceFilter;
      const transportMatched = transportTypeFilter === "all" || item.transportType === transportTypeFilter;
      return sourceMatched && transportMatched;
    });
  }, [searchValue, services, sourceFilter, transportTypeFilter]);

  const syncToolNamesToCards = useCallback((service: Pick<McpServiceItem, "mcpId" | "name" | "serverUrl">, tools: McpTool[]) => {
    const nextToolNames = tools.map((item) => item.name);
    setSelectedService((prev) => {
      if (!prev || prev.mcpId !== service.mcpId) {
        return prev;
      }
      if (isSameToolNames(prev.tools, nextToolNames)) {
        return prev;
      }
      return { ...prev, tools: nextToolNames };
    });

    setServices((prev) => {
      let changed = false;
      const next = prev.map((item) => {
        if (item.mcpId !== service.mcpId) {
          return item;
        }
        if (isSameToolNames(item.tools, nextToolNames)) {
          return item;
        }
        changed = true;
        return { ...item, tools: nextToolNames };
      });
      return changed ? next : prev;
    });
  }, []);

  const { toggleServiceStatus, togglingServiceId } = useMcpToolsToggle({
    loadServerList,
    setSelectedService,
    t,
    message,
  });

  const detail = useMcpToolsDetail({
    selectedService,
    onSelectedServiceChange: setSelectedService,
    onServicesReload: loadServerList,
    onSyncToolNames: syncToolNamesToCards,
    t,
    message,
  });

  return {
    searchValue,
    setSearchValue,
    sourceFilter,
    setSourceFilter,
    transportTypeFilter,
    setTransportTypeFilter,
    services,
    loadingServices: listQuery.isFetching && services.length === 0,
    selectedService,
    setSelectedService,
    showAddModal,
    setShowAddModal,
    loadServerList,
    filteredServices,
    toggleServiceStatus,
    togglingServiceId,
    detail,
  };
}
