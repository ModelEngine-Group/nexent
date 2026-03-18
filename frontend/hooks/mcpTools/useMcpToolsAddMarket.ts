import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import log from "@/lib/logger";
import { MCP_SERVER_TYPE, MCP_TAB } from "@/const/mcpTools";
import { addMcpToolService, fetchMarketMcpCards, type MarketMcpCard } from "@/services/mcpToolsService";
import {
  type AddMcpMarketActions,
  type AddMcpMarketState,
  type McpTab,
} from "@/types/mcpTools";

type UseMcpToolsAddMarketParams = {
  open: boolean;
  addModalTab: McpTab;
  t: (key: string) => string;
  message: MessageInstance;
  onServiceAdded: () => Promise<unknown>;
  onClose: () => void;
};

export function useMcpToolsAddMarket({
  open,
  addModalTab,
  t,
  message,
  onServiceAdded,
  onClose,
}: UseMcpToolsAddMarketParams) {
  const [marketSearchValue, setMarketSearchValue] = useState("");
  const [selectedMarketService, setSelectedMarketService] = useState<MarketMcpCard | null>(null);
  const [marketServices, setMarketServices] = useState<MarketMcpCard[]>([]);
  const [marketCurrentCursor, setMarketCurrentCursor] = useState<string | null>(null);
  const [marketNextCursor, setMarketNextCursor] = useState<string | null>(null);
  const [marketCursorHistory, setMarketCursorHistory] = useState<string[]>([]);
  const [marketPage, setMarketPage] = useState(1);
  const [marketVersion, setMarketVersion] = useState("latest");
  const [marketUpdatedSince, setMarketUpdatedSince] = useState("");
  const [marketIncludeDeleted, setMarketIncludeDeleted] = useState(false);
  const [addingService, setAddingService] = useState(false);

  const addMutation = useMutation({ mutationFn: addMcpToolService });

  const reset = useCallback(() => {
    setMarketSearchValue("");
    setMarketCurrentCursor(null);
    setMarketNextCursor(null);
    setMarketCursorHistory([]);
    setMarketPage(1);
    setMarketVersion("latest");
    setMarketUpdatedSince("");
    setMarketIncludeDeleted(false);
    setSelectedMarketService(null);
    setMarketServices([]);
    setAddingService(false);
  }, []);

  const loadMarketFirstPage = useCallback(() => {
    setMarketCurrentCursor(null);
    setMarketCursorHistory([]);
    setMarketPage(1);
  }, []);

  useEffect(() => {
    if (!(open && addModalTab === MCP_TAB.MARKET)) return;
    const timer = window.setTimeout(() => {
      loadMarketFirstPage();
    }, 350);
    return () => window.clearTimeout(timer);
  }, [
    open,
    addModalTab,
    marketSearchValue,
    marketVersion,
    marketUpdatedSince,
    marketIncludeDeleted,
    loadMarketFirstPage,
  ]);

  const marketQuery = useQuery<{ items: MarketMcpCard[]; nextCursor: string | null }>({
    queryKey: [
      "mcp-tools",
      "market",
      marketSearchValue,
      marketCurrentCursor,
      marketVersion,
      marketUpdatedSince,
      marketIncludeDeleted,
    ],
    enabled: open && addModalTab === MCP_TAB.MARKET,
    retry: false,
    queryFn: async () => {
      const result = await fetchMarketMcpCards({
        search: marketSearchValue,
        cursor: marketCurrentCursor,
        version: marketVersion,
        updatedSince: marketUpdatedSince,
        includeDeleted: marketIncludeDeleted,
      });
      if (!result.success) throw new Error(result.message || t("mcpTools.market.loadFailed"));
      return result.data;
    },
  });

  useEffect(() => {
    if (!marketQuery.data) return;
    setMarketServices(marketQuery.data.items);
    setMarketNextCursor(marketQuery.data.nextCursor);
  }, [marketQuery.data]);

  useEffect(() => {
    if (!(marketQuery.error instanceof Error)) return;
    log.error("[useMcpToolsAddMarket] Failed to load market MCP cards", {
      error: marketQuery.error,
      search: marketSearchValue,
      cursor: marketCurrentCursor,
      version: marketVersion,
      updatedSince: marketUpdatedSince,
      includeDeleted: marketIncludeDeleted,
    });
    message.error(marketQuery.error.message);
    setMarketServices([]);
    setMarketNextCursor(null);
  }, [
    marketQuery.error,
    marketSearchValue,
    marketCurrentCursor,
    marketVersion,
    marketUpdatedSince,
    marketIncludeDeleted,
    message,
  ]);

  const handleMarketNextPage = () => {
    if (!marketNextCursor || marketQuery.isFetching) return;
    const currentCursorSnapshot = marketCurrentCursor;
    setMarketCursorHistory((prev) => [...prev, currentCursorSnapshot ?? ""]);
    setMarketCurrentCursor(marketNextCursor);
    setMarketPage((prev) => prev + 1);
  };

  const handleMarketPrevPage = () => {
    if (marketCursorHistory.length === 0 || marketQuery.isFetching) return;
    const previousCursor = marketCursorHistory[marketCursorHistory.length - 1] || null;
    setMarketCursorHistory((prev) => prev.slice(0, -1));
    setMarketCurrentCursor(previousCursor);
    setMarketPage((prev) => Math.max(1, prev - 1));
  };

  const handleQuickAddFromMarket = async (service: MarketMcpCard) => {
    const isUrlService = service.serverType === MCP_SERVER_TYPE.HTTP || service.serverType === MCP_SERVER_TYPE.SSE;
    if (!isUrlService || !service.serverUrl.trim()) {
      log.error("[useMcpToolsAddMarket] Quick add is unsupported for selected market service", {
        serviceName: service.name,
        serverType: service.serverType,
        serverUrl: service.serverUrl,
      });
      message.error(t("mcpTools.market.quickAddUnsupported"));
      return;
    }

    setAddingService(true);
    try {
      const result = await addMutation.mutateAsync({
        name: service.name,
        description: service.description || t("mcpTools.service.defaultDescription"),
        source: MCP_TAB.MARKET,
        server_type: service.serverType,
        server_url: service.serverUrl,
        tags: [],
      });

      if (!result.success) throw new Error(result.message || t("mcpTools.add.failed"));
      await onServiceAdded();
      message.success(t("mcpTools.market.quickAddSuccess"));
      onClose();
    } catch (error) {
      const msg = error instanceof Error ? error.message : t("mcpTools.add.failed");
      log.error("[useMcpToolsAddMarket] Failed to quick add market service", {
        error,
        serviceName: service.name,
        serverType: service.serverType,
        serverUrl: service.serverUrl,
      });
      message.error(msg === "MCP connection failed" ? t("mcpTools.error.connectionFailed") : msg);
    } finally {
      setAddingService(false);
    }
  };

  const state: AddMcpMarketState = useMemo(
    () => ({
      marketSearchValue,
      selectedMarketService,
      filteredMarketServices: marketServices,
      marketLoading: marketQuery.isFetching,
      marketPage,
      hasPrevMarketPage: marketCursorHistory.length > 0,
      hasNextMarketPage: Boolean(marketNextCursor),
      marketVersion,
      marketUpdatedSince,
      marketIncludeDeleted,
    }),
    [
      marketSearchValue,
      selectedMarketService,
      marketServices,
      marketQuery.isFetching,
      marketPage,
      marketCursorHistory.length,
      marketNextCursor,
      marketVersion,
      marketUpdatedSince,
      marketIncludeDeleted,
    ]
  );

  const actions: AddMcpMarketActions = useMemo(
    () => ({
      onMarketSearchChange: setMarketSearchValue,
      onRefreshMarket: loadMarketFirstPage,
      onPrevMarketPage: handleMarketPrevPage,
      onNextMarketPage: handleMarketNextPage,
      onMarketVersionChange: setMarketVersion,
      onMarketUpdatedSinceChange: setMarketUpdatedSince,
      onMarketIncludeDeletedChange: setMarketIncludeDeleted,
      onSelectMarketService: setSelectedMarketService,
      onQuickAddFromMarket: handleQuickAddFromMarket,
    }),
    [loadMarketFirstPage]
  );

  return {
    state,
    actions,
    addingService,
    reset,
  };
}
