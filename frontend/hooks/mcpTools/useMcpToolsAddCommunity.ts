import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import log from "@/lib/logger";
import { MCP_TRANSPORT_TYPE, MCP_TAB } from "@/const/mcpTools";
import { ApiError } from "@/services/api";
import {
  addContainerMcpToolService,
  addMcpToolService,
  fetchCommunityMcpTagStats,
  fetchCommunityMcpCards,
} from "@/services/mcpToolsService";
import { ensureContainerPortAvailableOnce } from "./useContainerPortAvailability";
import {
  type AddMcpRuntimeFromConfigPayload,
  type CommunityMcpCard,
  type McpTagStat,
  type McpTransportType,
  type McpTab,
} from "@/types/mcpTools";

type UseMcpToolsAddCommunityParams = {
  open: boolean;
  addModalTab: McpTab;
  t: (key: string, params?: Record<string, unknown>) => string;
  message: MessageInstance;
  onServiceAdded: () => Promise<unknown>;
  onClose: () => void;
};

type CommunityQuickAddDraft = {
  name: string;
  description: string;
  transportType: McpTransportType;
  serverUrl: string;
  authorizationToken: string;
  containerConfigJson: string;
  containerPort: number | undefined;
  tags: string[];
  tagInputValue: string;
  version?: string;
  registryJson?: Record<string, unknown>;
};

const INITIAL_DRAFT: CommunityQuickAddDraft = {
  name: "",
  description: "",
  transportType: MCP_TRANSPORT_TYPE.HTTP,
  serverUrl: "",
  authorizationToken: "",
  containerConfigJson: "",
  containerPort: undefined,
  tags: [],
  tagInputValue: "",
  version: undefined,
  registryJson: undefined,
};

export function useMcpToolsAddCommunity({
  open,
  addModalTab,
  t,
  message,
  onServiceAdded,
  onClose,
}: UseMcpToolsAddCommunityParams) {
  const [communitySearchValue, setCommunitySearchValue] = useState("");
  const [communityTransportTypeFilter, setCommunityTransportTypeFilter] = useState<"all" | "http" | "sse" | "stdio">("all");
  const [communityTagFilter, setCommunityTagFilter] = useState<string>("all");
  const [selectedCommunityService, setSelectedCommunityService] = useState<CommunityMcpCard | null>(null);
  const [communityCurrentCursor, setCommunityCurrentCursor] = useState<string | null>(null);
  const [communityCursorHistory, setCommunityCursorHistory] = useState<string[]>([]);
  const [communityPage, setCommunityPage] = useState(1);
  const [quickAddConfirmVisible, setQuickAddConfirmVisible] = useState(false);
  const [quickAddSourceService, setQuickAddSourceService] = useState<CommunityMcpCard | null>(null);
  const [quickAddDraft, setQuickAddDraft] = useState<CommunityQuickAddDraft>(INITIAL_DRAFT);
  const [addingService, setAddingService] = useState(false);
  const communityPageSize = 30;

  const addMutation = useMutation({ mutationFn: addMcpToolService });

  const reset = useCallback(() => {
    setCommunitySearchValue("");
    setCommunityTransportTypeFilter("all");
    setCommunityTagFilter("all");
    setCommunityCurrentCursor(null);
    setCommunityCursorHistory([]);
    setCommunityPage(1);
    setSelectedCommunityService(null);
    setQuickAddConfirmVisible(false);
    setQuickAddSourceService(null);
    setQuickAddDraft(INITIAL_DRAFT);
    setAddingService(false);
  }, []);

  const loadCommunityFirstPage = useCallback(() => {
    setCommunityCurrentCursor(null);
    setCommunityCursorHistory([]);
    setCommunityPage(1);
  }, []);

  useEffect(() => {
    if (!(open && addModalTab === MCP_TAB.COMMUNITY)) return;
    const timer = window.setTimeout(() => {
      loadCommunityFirstPage();
    }, 350);
    return () => window.clearTimeout(timer);
  }, [open, addModalTab, communitySearchValue, communityTransportTypeFilter, communityTagFilter, loadCommunityFirstPage]);

  const communityQuery = useQuery<{ items: CommunityMcpCard[]; nextCursor: string | null }>({
    queryKey: ["mcp-tools", "community", communitySearchValue, communityTransportTypeFilter, communityTagFilter, communityCurrentCursor],
    enabled: open && addModalTab === MCP_TAB.COMMUNITY,
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: async () => {
      const result = await fetchCommunityMcpCards({
        search: communitySearchValue,
        cursor: communityCurrentCursor,
        transportType: communityTransportTypeFilter === "all" ? undefined : communityTransportTypeFilter,
        tag: communityTagFilter === "all" ? undefined : communityTagFilter,
        limit: communityPageSize,
      });
      return result.data;
    },
  });

  const communityTagStatsQuery = useQuery<McpTagStat[]>({
    queryKey: ["mcp-tools", "community-tag-stats"],
    enabled: open && addModalTab === MCP_TAB.COMMUNITY,
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: async () => {
      const result = await fetchCommunityMcpTagStats();
      return result.data;
    },
  });

  const communityServices = communityQuery.data?.items ?? [];
  const communityNextCursor = communityQuery.data?.nextCursor ?? null;
  const communityTagStats = communityTagStatsQuery.data || [];

  const updateQuickAddDraft = useCallback((next: Partial<CommunityQuickAddDraft>) => {
    setQuickAddDraft((prev) => ({ ...prev, ...next }));
  }, []);

  useEffect(() => {
    if (!(communityQuery.error instanceof Error)) return;
    log.error("[useMcpToolsAddCommunity] Failed to load community MCP cards", {
      error: communityQuery.error,
      search: communitySearchValue,
      cursor: communityCurrentCursor,
    });
    message.error(t("mcpTools.community.loadFailed"));
  }, [communityQuery.error, communitySearchValue, communityCurrentCursor, message, t]);

  useEffect(() => {
    if (!(communityTagStatsQuery.error instanceof Error)) return;
    log.error("[useMcpToolsAddCommunity] Failed to load community MCP tag stats", {
      error: communityTagStatsQuery.error,
    });
  }, [communityTagStatsQuery.error]);

  const handleCommunityNextPage = useCallback(() => {
    if (!communityNextCursor || communityQuery.isFetching) return;
    const currentCursorSnapshot = communityCurrentCursor;
    setCommunityCursorHistory((prev) => [...prev, currentCursorSnapshot ?? ""]);
    setCommunityCurrentCursor(communityNextCursor);
    setCommunityPage((prev) => prev + 1);
  }, [communityCurrentCursor, communityNextCursor, communityQuery.isFetching]);

  const handleCommunityPrevPage = useCallback(() => {
    if (communityCursorHistory.length === 0 || communityQuery.isFetching) return;
    const previousCursor = communityCursorHistory[communityCursorHistory.length - 1] || null;
    setCommunityCursorHistory((prev) => prev.slice(0, -1));
    setCommunityCurrentCursor(previousCursor);
    setCommunityPage((prev) => Math.max(1, prev - 1));
  }, [communityCursorHistory, communityQuery.isFetching]);

  const handleQuickAddFromCommunity = useCallback((service: CommunityMcpCard) => {
    const transportType = (service.transportType || MCP_TRANSPORT_TYPE.HTTP) as McpTransportType;
    const nextConfig = service.configJson && typeof service.configJson === "object"
      ? JSON.stringify(service.configJson, null, 2)
      : "";

    setQuickAddSourceService(service);
    setQuickAddDraft({
      name: service.name || "",
      description: service.description || "",
      transportType,
      serverUrl: service.serverUrl || "",
      authorizationToken: "",
      containerConfigJson: nextConfig,
      containerPort: undefined,
      tags: service.tags || [],
      tagInputValue: "",
      version: service.version || undefined,
      registryJson: service.registryJson || undefined,
    });
    setQuickAddConfirmVisible(true);
  }, []);

  const addQuickAddTag = useCallback(() => {
    const tag = quickAddDraft.tagInputValue.trim();
    if (!tag) return;
    setQuickAddDraft((prev) => ({
      ...prev,
      tags: prev.tags.includes(tag) ? prev.tags : [...prev.tags, tag],
      tagInputValue: "",
    }));
  }, [quickAddDraft.tagInputValue]);

  const removeQuickAddTag = useCallback((index: number) => {
    setQuickAddDraft((prev) => ({
      ...prev,
      tags: prev.tags.filter((_, idx) => idx !== index),
    }));
  }, []);

  const handleCloseQuickAddConfirm = useCallback(() => {
    if (addingService) return;
    setQuickAddConfirmVisible(false);
    setQuickAddSourceService(null);
    setQuickAddDraft(INITIAL_DRAFT);
  }, [addingService]);

  const handleConfirmQuickAddFromCommunity = useCallback(async () => {
    const draft = quickAddDraft;
    const serviceName = draft.name.trim();
    const transportType = draft.transportType;
    const serverUrl = draft.serverUrl.trim();

    setAddingService(true);
    try {
      if (transportType === MCP_TRANSPORT_TYPE.STDIO) {
        let parsedConfig: unknown;
        try {
          parsedConfig = JSON.parse(draft.containerConfigJson);
        } catch {
          message.error(t("mcpTools.add.error.containerJsonInvalid"));
          return;
        }

        const mcpConfig = parsedConfig as AddMcpRuntimeFromConfigPayload;
        if (!mcpConfig.mcpServers || typeof mcpConfig.mcpServers !== "object") {
          message.error(t("mcpTools.add.validate.containerConfigRequired"));
          return;
        }

        const available = await ensureContainerPortAvailableOnce({
          containerPort: draft.containerPort,
          message,
          t,
        });
        if (!available) {
          return;
        }

        await addContainerMcpToolService({
          name: serviceName,
          description: draft.description.trim(),
          source: "community",
          tags: draft.tags,
          authorization_token: draft.authorizationToken.trim() || undefined,
          registry_json: draft.registryJson,
          port: draft.containerPort as number,
          mcp_config: mcpConfig,
        });
      } else {
        await addMutation.mutateAsync({
          name: serviceName,
          description: draft.description.trim(),
          source: MCP_TAB.COMMUNITY,
          transport_type: transportType === MCP_TRANSPORT_TYPE.SSE ? MCP_TRANSPORT_TYPE.SSE : MCP_TRANSPORT_TYPE.HTTP,
          server_url: serverUrl,
          tags: draft.tags,
          authorization_token: draft.authorizationToken.trim() || undefined,
          version: draft.version || undefined,
          registry_json: draft.registryJson,
        });
      }

      await onServiceAdded();
      message.success(t("mcpTools.community.quickAddSuccess"));
      onClose();
    } catch (error) {
      log.error("[useMcpToolsAddCommunity] Failed to quick add community service", {
        error,
        serviceName,
        transportType,
      });
      if (error instanceof ApiError && Number(error.code) === 409) {
        message.error(t("mcpTools.add.enableNameConflict"));
      } else {
        message.error(t("mcpTools.add.failed"));
      }
    } finally {
      setAddingService(false);
    }
  }, [addMutation, message, onClose, onServiceAdded, quickAddDraft, t]);

  return {
    communitySearchValue,
    communityTransportTypeFilter,
    communityTagFilter,
    communityTagStats,
    selectedCommunityService,
    filteredCommunityServices: communityServices,
    communityLoading: communityQuery.isFetching,
    communityPage,
    hasPrevCommunityPage: communityCursorHistory.length > 0,
    hasNextCommunityPage: Boolean(communityNextCursor),
    quickAddSubmitting: addingService,
    quickAddConfirmVisible,
    quickAddSourceService,
    quickAddDraft,
    setCommunitySearchValue,
    setCommunityTransportTypeFilter,
    setCommunityTagFilter,
    setSelectedCommunityService,
    updateQuickAddDraft,
    addQuickAddTag,
    removeQuickAddTag,
    handleCommunityPrevPage,
    handleCommunityNextPage,
    handleQuickAddFromCommunity,
    handleCloseQuickAddConfirm,
    handleConfirmQuickAddFromCommunity,
    addingService,
    reset,
  };
}
