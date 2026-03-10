"use client";

import React, { useEffect, useMemo, useState } from "react";
import { App, Input, Button } from "antd";
import type { UploadFile } from "antd/es/upload/interface";
import { useTranslation } from "react-i18next";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import McpToolListModal from "./components/McpToolListModal";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import AddMcpServiceModal from "./components/AddMcpServiceModal";
import type { McpTool } from "@/types/agentConfig";

type McpTab = "本地" | "公共市场";
type McpServerType = "HTTP" | "SSE" | "容器";
type McpServiceStatus = "已启用" | "未启用";
type McpHealthStatus = "正常" | "异常" | "未检测";
type McpContainerStatus = "运行中" | "已停止" | "未知";

const MCP_TAB = { LOCAL: "本地", MARKET: "公共市场" } as const;
const MCP_SERVER_TYPE = { HTTP: "HTTP", SSE: "SSE", CONTAINER: "容器" } as const;
const MCP_SERVICE_STATUS = { ENABLED: "已启用", DISABLED: "未启用" } as const;
const MCP_HEALTH_STATUS = { HEALTHY: "正常", UNHEALTHY: "异常", UNCHECKED: "未检测" } as const;

const normalizeMcpTab = (value: unknown): McpTab => {
  return value === MCP_TAB.MARKET ? MCP_TAB.MARKET : MCP_TAB.LOCAL;
};

const normalizeMcpServerType = (value: unknown): McpServerType => {
  if (value === MCP_SERVER_TYPE.SSE) return MCP_SERVER_TYPE.SSE;
  return value === MCP_SERVER_TYPE.CONTAINER ? MCP_SERVER_TYPE.CONTAINER : MCP_SERVER_TYPE.HTTP;
};

const normalizeMcpServiceStatus = (value: unknown): McpServiceStatus => {
  return value === MCP_SERVICE_STATUS.ENABLED ? MCP_SERVICE_STATUS.ENABLED : MCP_SERVICE_STATUS.DISABLED;
};

const normalizeMcpHealthStatus = (value: unknown): McpHealthStatus => {
  if (value === MCP_HEALTH_STATUS.HEALTHY) return MCP_HEALTH_STATUS.HEALTHY;
  if (value === MCP_HEALTH_STATUS.UNHEALTHY) return MCP_HEALTH_STATUS.UNHEALTHY;
  return MCP_HEALTH_STATUS.UNCHECKED;
};

const normalizeMcpContainerStatus = (value: unknown): McpContainerStatus => {
  if (value === "运行中") return "运行中";
  if (value === "已停止") return "已停止";
  return "未知";
};

const normalizeMarketServerStatus = (value: unknown): string => {
  if (typeof value !== "string") return "unknown";
  const normalized = value.trim().toLowerCase();
  if (normalized === "active") return "active";
  if (normalized === "deprecated") return "deprecated";
  return "unknown";
};

type McpCard = {
  name: string;
  description: string;
  source: McpTab;
  status: McpServiceStatus;
  updatedAt: string;
  tags: string[];
  serverType: McpServerType;
  serverUrl: string;
  tools: string[];
  healthStatus: McpHealthStatus;
  containerStatus?: McpContainerStatus;
  authorizationToken?: string;
};

type MarketMcpCard = {
  name: string;
  title: string;
  version: string;
  description: string;
  publishedAt: string;
  status: string;
  websiteUrl: string;
  remotes: Array<{ type: string; url: string }>;
  serverJson: Record<string, unknown>;
  serverType: McpServerType;
  serverUrl: string;
};

const getAuthHeaders = () => {
  const session = typeof window !== "undefined" ? localStorage.getItem("session") : null;
  const sessionObj = session ? JSON.parse(session) : null;

  return {
    "Content-Type": "application/json",
    "User-Agent": "AgentFrontEnd/1.0",
    ...(sessionObj?.access_token && { Authorization: `Bearer ${sessionObj.access_token}` }),
  };
};

export default function McpToolsContent() {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const { confirm } = useConfirmModal();
  const [searchValue, setSearchValue] = useState("");
  const [marketSearchValue, setMarketSearchValue] = useState("");
  const [selectedService, setSelectedService] = useState<McpCard | null>(null);
  const [services, setServices] = useState<McpCard[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draftService, setDraftService] = useState<McpCard | null>(null);
  const [healthCheckLoading, setHealthCheckLoading] = useState(false);
  const [tagDrafts, setTagDrafts] = useState<string[]>([]);
  const [tagInputValue, setTagInputValue] = useState("");
  const [showAddModal, setShowAddModal] = useState(false);
  const [newServiceName, setNewServiceName] = useState("");
  const [newServiceUrl, setNewServiceUrl] = useState("");
  const [newServiceDesc, setNewServiceDesc] = useState("");
  const [newServiceAuthorizationToken, setNewServiceAuthorizationToken] = useState("");
  const [newServerType, setNewServerType] = useState<McpServerType>(MCP_SERVER_TYPE.HTTP);
  const [containerConfigJson, setContainerConfigJson] = useState("");
  const [containerUploadFileList, setContainerUploadFileList] = useState<UploadFile[]>([]);
  const [containerPort, setContainerPort] = useState<number | undefined>(undefined);
  const [containerServiceName, setContainerServiceName] = useState("");
  const [newTagDrafts, setNewTagDrafts] = useState<string[]>([]);
  const [newTagInputValue, setNewTagInputValue] = useState("");
  const [addModalTab, setAddModalTab] = useState<McpTab>(MCP_TAB.LOCAL);
  const [selectedMarketService, setSelectedMarketService] = useState<MarketMcpCard | null>(null);
  const [marketServices, setMarketServices] = useState<MarketMcpCard[]>([]);
  const [marketLoading, setMarketLoading] = useState(false);
  const [marketCurrentCursor, setMarketCurrentCursor] = useState<string | null>(null);
  const [marketNextCursor, setMarketNextCursor] = useState<string | null>(null);
  const [marketCursorHistory, setMarketCursorHistory] = useState<string[]>([]);
  const [marketPage, setMarketPage] = useState(1);
  const [marketVersion, setMarketVersion] = useState("latest");
  const [marketUpdatedSince, setMarketUpdatedSince] = useState("");
  const [marketIncludeDeleted, setMarketIncludeDeleted] = useState(false);
  const [addingService, setAddingService] = useState(false);
  const [loadingTools, setLoadingTools] = useState(false);
  const [toolsModalVisible, setToolsModalVisible] = useState(false);
  const [currentServerTools, setCurrentServerTools] = useState<McpTool[]>([]);
  const [toolCache, setToolCache] = useState<Record<string, McpTool[]>>({});

  const getToolCacheKey = (service: Pick<McpCard, "name" | "serverUrl">) =>
    `${service.name}@@${service.serverUrl}`;

  const syncToolNamesToCards = (service: McpCard, tools: McpTool[]) => {
    const nextToolNames = tools.map((item) => item.name);
    setDraftService((prev) => {
      if (!prev || prev.name !== service.name || prev.serverUrl !== service.serverUrl) {
        return prev;
      }
      return { ...prev, tools: nextToolNames };
    });
    setServices((prev) =>
      prev.map((item) =>
        item.name === service.name && item.serverUrl === service.serverUrl
          ? { ...item, tools: nextToolNames }
          : item
      )
    );
  };

  const resetAddForm = () => {
    setNewServiceName("");
    setNewServiceUrl("");
    setNewServiceDesc("");
    setNewServiceAuthorizationToken("");
    setNewServerType(MCP_SERVER_TYPE.HTTP);
    setContainerConfigJson("");
    setContainerUploadFileList([]);
    setContainerPort(undefined);
    setContainerServiceName("");
    setNewTagDrafts([]);
    setNewTagInputValue("");
  };

  const closeAddModal = () => {
    setShowAddModal(false);
    setAddModalTab(MCP_TAB.LOCAL);
    setMarketSearchValue("");
    setMarketCurrentCursor(null);
    setMarketNextCursor(null);
    setMarketCursorHistory([]);
    setMarketPage(1);
    setMarketVersion("latest");
    setMarketUpdatedSince("");
    setMarketIncludeDeleted(false);
    setSelectedMarketService(null);
    resetAddForm();
  };

  const fetchServices = async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const response = await fetch("/api/mcp-tools/list", {
        headers: getAuthHeaders(),
      });
      const data = await response.json();

      if (!response.ok || data?.status !== "success") {
        throw new Error(data?.message || t("mcpTools.list.loadFailed"));
      }

      if (!Array.isArray(data?.data)) {
        throw new Error(t("mcpTools.list.invalidFormat"));
      }

      const normalizedCards = data.data.map((item: any) => ({
        name: typeof item?.name === "string" ? item.name : "",
        description:
          typeof item?.description === "string" && item.description.trim().length > 0
            ? item.description
            : t("mcpTools.service.defaultDescription"),
        source: normalizeMcpTab(item?.source),
        status: normalizeMcpServiceStatus(item?.status),
        updatedAt: typeof item?.updatedAt === "string" ? item.updatedAt : "",
        tags: Array.isArray(item?.tags) ? item.tags.filter((tag: unknown) => typeof tag === "string") : [],
        serverType: normalizeMcpServerType(item?.serverType),
        serverUrl: typeof item?.serverUrl === "string" ? item.serverUrl : "",
        tools: Array.isArray(item?.tools) ? item.tools.filter((tool: unknown) => typeof tool === "string") : [],
        healthStatus: normalizeMcpHealthStatus(item?.healthStatus),
        containerStatus: item?.containerStatus ? normalizeMcpContainerStatus(item.containerStatus) : undefined,
        authorizationToken: typeof item?.authorizationToken === "string" ? item.authorizationToken : undefined,
      } as McpCard));

      setServices(normalizedCards);
    } catch (error) {
      const messageText = error instanceof Error ? error.message : t("mcpTools.list.loadFailed");
      setLoadError(messageText);
      message.error(messageText);
    } finally {
      setIsLoading(false);
    }
  };

  const fetchMarketServices = async (options?: {
    search?: string;
    cursor?: string | null;
    version?: string;
    updatedSince?: string;
    includeDeleted?: boolean;
  }) => {
    setMarketLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", "30");
      const searchValue = (options?.search ?? marketSearchValue).trim();
      if (searchValue) {
        params.set("search", searchValue);
      }
      const versionValue = (options?.version ?? marketVersion).trim();
      if (versionValue) {
        params.set("version", versionValue);
      }
      const updatedSinceValue = (options?.updatedSince ?? marketUpdatedSince).trim();
      if (updatedSinceValue) {
        params.set("updated_since", updatedSinceValue);
      }
      const includeDeletedValue = options?.includeDeleted ?? marketIncludeDeleted;
      params.set("include_deleted", includeDeletedValue ? "true" : "false");
      const cursorValue = options?.cursor;
      if (cursorValue) {
        params.set("cursor", cursorValue);
      }

      const response = await fetch(`/api/mcp-tools/market/list?${params.toString()}`, {
        headers: getAuthHeaders(),
      });
      const data = await response.json();

      if (!response.ok || data?.status !== "success") {
        throw new Error(data?.detail || data?.message || t("mcpTools.market.loadFailed"));
      }

      const items = Array.isArray(data?.data?.items) ? data.data.items : [];
      const normalized = items
        .map((item: any) => ({
          name: typeof item?.name === "string" ? item.name : "",
          title: typeof item?.title === "string" ? item.title : "",
          version: typeof item?.version === "string" ? item.version : "",
          description: typeof item?.description === "string" ? item.description : t("mcpTools.service.defaultDescription"),
          publishedAt: typeof item?.publishedAt === "string" ? item.publishedAt : "",
          status: normalizeMarketServerStatus(item?.status),
          websiteUrl: typeof item?.websiteUrl === "string" ? item.websiteUrl : "",
          remotes: Array.isArray(item?.remotes)
            ? item.remotes
                .map((remote: any) => ({
                  type: typeof remote?.type === "string" ? remote.type : "",
                  url: typeof remote?.url === "string" ? remote.url : "",
                }))
                .filter((remote: { type: string; url: string }) => remote.url.length > 0)
            : [],
          serverJson: typeof item?.serverJson === "object" && item?.serverJson ? item.serverJson : {},
          serverType: normalizeMcpServerType(item?.serverType),
          serverUrl: typeof item?.serverUrl === "string" ? item.serverUrl : "",
        }))
        .filter((item: MarketMcpCard) => item.name.trim().length > 0);

      setMarketServices(normalized);
      setMarketNextCursor(typeof data?.data?.nextCursor === "string" && data.data.nextCursor.trim() ? data.data.nextCursor : null);
    } catch (error) {
      const messageText = error instanceof Error ? error.message : t("mcpTools.market.loadFailed");
      message.error(messageText);
      setMarketServices([]);
      setMarketNextCursor(null);
    } finally {
      setMarketLoading(false);
    }
  };

  const loadMarketFirstPage = async (search?: string) => {
    setMarketCurrentCursor(null);
    setMarketCursorHistory([]);
    setMarketPage(1);
    await fetchMarketServices({ search, cursor: null });
  };

  const handleMarketNextPage = async () => {
    if (!marketNextCursor || marketLoading) {
      return;
    }
    const nextCursor = marketNextCursor;
    const currentCursorSnapshot = marketCurrentCursor;
    setMarketCursorHistory((prev) => [...prev, currentCursorSnapshot ?? ""]);
    setMarketCurrentCursor(nextCursor);
    setMarketPage((prev) => prev + 1);
    await fetchMarketServices({ cursor: nextCursor });
  };

  const handleMarketPrevPage = async () => {
    if (marketCursorHistory.length === 0 || marketLoading) {
      return;
    }
    const previousCursor = marketCursorHistory[marketCursorHistory.length - 1] || null;
    setMarketCursorHistory((prev) => prev.slice(0, -1));
    setMarketCurrentCursor(previousCursor);
    setMarketPage((prev) => Math.max(1, prev - 1));
    await fetchMarketServices({ cursor: previousCursor });
  };

  const handleAddService = async () => {
    if (!newServiceName.trim()) {
      message.error(t("mcpTools.add.validate.nameRequired"));
      return;
    }

    if ((newServerType === MCP_SERVER_TYPE.HTTP || newServerType === MCP_SERVER_TYPE.SSE) && !newServiceUrl.trim()) {
      message.error(t("mcpTools.add.validate.httpUrlRequired"));
      return;
    }

    if (newServerType === MCP_SERVER_TYPE.CONTAINER) {
      const hasConfig = containerConfigJson.trim().length > 0 || containerUploadFileList.length > 0;
      if (!hasConfig) {
        message.error(t("mcpTools.add.validate.containerConfigRequired"));
        return;
      }
      if (!containerServiceName.trim() || !containerPort) {
        message.error(t("mcpTools.add.validate.containerRequired"));
        return;
      }
    }

    if (addModalTab !== MCP_TAB.LOCAL) {
      message.error(t("mcpTools.add.validate.localTabOnly"));
      return;
    }

    const tags = newTagDrafts.map((tag) => tag.trim()).filter((tag) => tag.length > 0);
    const normalizedToken = newServiceAuthorizationToken.trim() || undefined;

    setAddingService(true);
    try {
      let finalServerUrl =
        (newServerType === MCP_SERVER_TYPE.HTTP || newServerType === MCP_SERVER_TYPE.SSE)
          ? newServiceUrl.trim()
          : `container://${containerServiceName.trim()}:${containerPort}`;
      const containerConfigPayload: Record<string, unknown> = {
        config_json: containerConfigJson.trim() || undefined,
        service_name: containerServiceName.trim() || undefined,
        port: containerPort,
      };

      if (newServerType === MCP_SERVER_TYPE.CONTAINER) {
        if (containerUploadFileList.length > 0) {
          const file = containerUploadFileList[0]?.originFileObj;
          if (!file) {
            throw new Error(t("mcpTools.add.error.imageReadFailed"));
          }
          const formData = new FormData();
          formData.append("file", file);
          formData.append("port", String(containerPort));
          formData.append("service_name", containerServiceName.trim());
          if (normalizedToken) {
            formData.append("env_vars", JSON.stringify({ authorization_token: normalizedToken }));
          }

          const uploadHeaders = getAuthHeaders();
          delete (uploadHeaders as Record<string, string>)["Content-Type"];

          const uploadResponse = await fetch("/api/mcp/upload-image", {
            method: "POST",
            headers: uploadHeaders,
            body: formData,
          });
          const uploadData = await uploadResponse.json();
          if (!uploadResponse.ok || uploadData?.status !== "success") {
            throw new Error(uploadData?.detail || uploadData?.message || t("mcpTools.add.error.imageUploadFailed"));
          }
          finalServerUrl = uploadData?.mcp_url || finalServerUrl;
          containerConfigPayload.upload_result = uploadData;
        } else {
          let parsedConfig: any;
          try {
            parsedConfig = JSON.parse(containerConfigJson);
          } catch {
            throw new Error(t("mcpTools.add.error.containerJsonInvalid"));
          }

          if (!parsedConfig?.mcpServers || typeof parsedConfig.mcpServers !== "object") {
            throw new Error(t("mcpTools.add.error.containerJsonMissingServers"));
          }

          const mcpServers = Object.fromEntries(
            Object.entries(parsedConfig.mcpServers as Record<string, any>).map(([key, value]) => [
              key,
              {
                ...value,
                port: value?.port ?? containerPort,
              },
            ])
          );

          const addConfigResponse = await fetch("/api/mcp/add-from-config", {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ mcpServers }),
          });
          const addConfigData = await addConfigResponse.json();
          if (!addConfigResponse.ok || addConfigData?.status !== "success") {
            throw new Error(addConfigData?.detail || addConfigData?.message || t("mcpTools.add.error.containerAddFailed"));
          }

          const firstResult = Array.isArray(addConfigData?.results) ? addConfigData.results[0] : undefined;
          finalServerUrl = firstResult?.mcp_url || finalServerUrl;
          containerConfigPayload.add_from_config_result = addConfigData;
        }
      }

      const response = await fetch("/api/mcp-tools/add", {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          name: newServiceName.trim(),
          description: newServiceDesc.trim() || t("mcpTools.service.defaultDescription"),
          source: addModalTab,
          server_type: newServerType,
          server_url: finalServerUrl,
          tags,
          authorization_token: normalizedToken,
          container_config: newServerType === MCP_SERVER_TYPE.CONTAINER ? containerConfigPayload : undefined,
        }),
      });
      const data = await response.json();

      if (!response.ok || data?.status !== "success") {
        throw new Error(data?.detail || data?.message || t("mcpTools.add.failed"));
      }

      setShowAddModal(false);
      resetAddForm();
      await fetchServices();
      message.success(t("mcpTools.add.success"));
    } catch (error) {
      const messageText = error instanceof Error ? error.message : t("mcpTools.add.failed");
      const displayMessage = messageText === "MCP connection failed" ? t("mcpTools.error.connectionFailed") : messageText;
      setLoadError(displayMessage);
      message.error(displayMessage);
    } finally {
      setAddingService(false);
    }
  };

  const handleQuickAddFromMarket = async (service: MarketMcpCard) => {
    const isUrlService = service.serverType === MCP_SERVER_TYPE.HTTP || service.serverType === MCP_SERVER_TYPE.SSE;
    if (!isUrlService || !service.serverUrl.trim()) {
      message.error(t("mcpTools.market.quickAddUnsupported"));
      return;
    }

    setAddingService(true);
    try {
      const response = await fetch("/api/mcp-tools/add", {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          name: service.name,
          description: service.description || t("mcpTools.service.defaultDescription"),
          source: MCP_TAB.MARKET,
          server_type: service.serverType,
          server_url: service.serverUrl,
          tags: [],
        }),
      });
      const data = await response.json();

      if (!response.ok || data?.status !== "success") {
        throw new Error(data?.detail || data?.message || t("mcpTools.add.failed"));
      }

      await fetchServices();
      closeAddModal();
      message.success(t("mcpTools.market.quickAddSuccess"));
    } catch (error) {
      const messageText = error instanceof Error ? error.message : t("mcpTools.add.failed");
      const displayMessage = messageText === "MCP connection failed" ? t("mcpTools.error.connectionFailed") : messageText;
      setLoadError(displayMessage);
      message.error(displayMessage);
    } finally {
      setAddingService(false);
    }
  };

  const normalizeTools = (tools: unknown): McpTool[] => {
    if (!Array.isArray(tools)) {
      return [];
    }
    return tools
      .map((item) => {
        const tool = item as Record<string, unknown>;
        const name = typeof tool.name === "string" ? tool.name : "";
        const description = typeof tool.description === "string" ? tool.description : "";
        if (!name.trim()) {
          return null;
        }
        return {
          name,
          description,
          parameters: tool.parameters,
        } as McpTool;
      })
      .filter((item): item is McpTool => item !== null);
  };

  const loadToolsForService = async (
    service: McpCard,
    options?: { silent?: boolean; force?: boolean }
  ) => {
    if (!service.name || !service.serverUrl) {
      return;
    }

    const silent = options?.silent ?? false;
    const force = options?.force ?? false;
    const cacheKey = getToolCacheKey(service);
    const cachedTools = toolCache[cacheKey];

    if (!force && cachedTools) {
      setCurrentServerTools(cachedTools);
      syncToolNamesToCards(service, cachedTools);
      return;
    }

    setLoadingTools(true);
    try {
      const response = await fetch(
        `/api/mcp/tools?service_name=${encodeURIComponent(service.name)}&mcp_url=${encodeURIComponent(service.serverUrl)}`,
        {
          method: "POST",
          headers: getAuthHeaders(),
        }
      );
      const data = await response.json();

      if (!response.ok || data?.status !== "success") {
        throw new Error(data?.detail || data?.message || t("mcpTools.tools.loadFailed"));
      }

      const nextTools = normalizeTools(data?.tools);
      setToolCache((prev) => ({ ...prev, [cacheKey]: nextTools }));
      setCurrentServerTools(nextTools);
      syncToolNamesToCards(service, nextTools);
    } catch (error) {
      if (!silent) {
        const messageText = error instanceof Error ? error.message : t("mcpTools.tools.loadFailed");
        message.error(messageText);
      }
      setCurrentServerTools(cachedTools ?? []);
    } finally {
      setLoadingTools(false);
    }
  };

  useEffect(() => {
    fetchServices().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (showAddModal && addModalTab === MCP_TAB.MARKET && marketServices.length === 0 && !marketLoading) {
      loadMarketFirstPage(marketSearchValue).catch(() => undefined);
    }
  }, [showAddModal, addModalTab, marketServices.length, marketLoading]);

  useEffect(() => {
    if (!(showAddModal && addModalTab === MCP_TAB.MARKET)) {
      return;
    }
    const timer = window.setTimeout(() => {
      loadMarketFirstPage(marketSearchValue).catch(() => undefined);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [marketSearchValue, marketVersion, marketUpdatedSince, marketIncludeDeleted, showAddModal, addModalTab]);

  useEffect(() => {
    if (selectedService) {
      setDraftService({ ...selectedService });
      setTagDrafts(selectedService.tags);
      setTagInputValue("");
      setCurrentServerTools(toolCache[getToolCacheKey(selectedService)] ?? []);
    } else {
      setDraftService(null);
      setTagDrafts([]);
      setTagInputValue("");
      setCurrentServerTools([]);
      setToolsModalVisible(false);
    }
  }, [selectedService]);

  const handleViewTools = () => {
    if (!draftService) {
      return;
    }
    setToolsModalVisible(true);
    loadToolsForService(draftService, { force: false }).catch(() => undefined);
  };

  const handleRefreshTools = () => {
    if (!draftService) {
      return;
    }
    loadToolsForService(draftService, { force: true }).catch(() => undefined);
  };

  const addDetailTag = () => {
    const nextTag = tagInputValue.trim();
    if (!nextTag) return;
    setTagDrafts((prev) => (prev.includes(nextTag) ? prev : [...prev, nextTag]));
    setTagInputValue("");
  };

  const addNewTag = () => {
    const nextTag = newTagInputValue.trim();
    if (!nextTag) return;
    setNewTagDrafts((prev) => (prev.includes(nextTag) ? prev : [...prev, nextTag]));
    setNewTagInputValue("");
  };

  const handleEnableToggle = async (service: McpCard) => {
    const nextEnabled = service.status !== MCP_SERVICE_STATUS.ENABLED;
    try {
      const response = await fetch("/api/mcp-tools/manage/enable", {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ name: service.name, enabled: nextEnabled }),
      });
      const data = await response.json();

      if (!response.ok || data?.status !== "success") {
        throw new Error(data?.message || t("mcpTools.service.toggleFailed"));
      }

      setServices((prev) =>
        prev.map((item) =>
          item.name === service.name
            ? { ...item, status: nextEnabled ? MCP_SERVICE_STATUS.ENABLED : MCP_SERVICE_STATUS.DISABLED }
            : item
        )
      );
      setSelectedService((prev) =>
        prev && prev.name === service.name
          ? { ...prev, status: nextEnabled ? MCP_SERVICE_STATUS.ENABLED : MCP_SERVICE_STATUS.DISABLED }
          : prev
      );
      message.success(
        nextEnabled
          ? t("mcpTools.service.enabled")
          : t("mcpTools.service.disabled")
      );
    } catch (error) {
      const messageText = error instanceof Error ? error.message : t("mcpTools.service.toggleFailed");
      const displayMessage = messageText === "MCP connection failed" ? t("mcpTools.error.connectionFailed") : messageText;
      setLoadError(displayMessage);
      message.error(displayMessage);
    }
  };

  const handleSaveUpdates = async () => {
    if (!selectedService || !draftService) return;
    const nextTags = tagDrafts.map((tag) => tag.trim()).filter((tag) => tag.length > 0);

    try {
      const response = await fetch("/api/mcp-tools/update", {
        method: "PUT",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          current_name: selectedService.name,
          name: draftService.name,
          description: draftService.description,
          server_url: draftService.serverUrl,
          authorization_token: draftService.authorizationToken ?? "",
          tags: nextTags,
        }),
      });
      const data = await response.json();

      if (!response.ok || data?.status !== "success") {
        throw new Error(data?.message || t("mcpTools.service.saveFailed"));
      }

      const updatedService = {
        ...draftService,
        tags: nextTags,
      };

      const oldCacheKey = getToolCacheKey(selectedService);
      const newCacheKey = getToolCacheKey(updatedService);
      if (oldCacheKey !== newCacheKey) {
        setToolCache((prev) => {
          if (!prev[oldCacheKey]) {
            return prev;
          }
          const { [oldCacheKey]: movedTools, ...rest } = prev;
          return { ...rest, [newCacheKey]: movedTools };
        });
      }

      setServices((prev) =>
        prev.map((item) =>
          item.name === selectedService.name ? updatedService : item
        )
      );
      setSelectedService(updatedService);
      setDraftService(updatedService);
      setTagDrafts(nextTags);
      message.success(t("mcpTools.service.saveSuccess"));
    } catch (error) {
      const messageText = error instanceof Error ? error.message : t("mcpTools.service.saveFailed");
      const displayMessage = messageText === "MCP connection failed" ? t("mcpTools.error.connectionFailed") : messageText;
      setLoadError(displayMessage);
      message.error(displayMessage);
    }
  };

  const handleHealthCheck = async () => {
    if (!draftService) return;
    setHealthCheckLoading(true);
    try {
      const response = await fetch("/api/mcp-tools/healthcheck", {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          name: draftService.name,
          server_url: draftService.serverUrl,
        }),
      });
      const data = await response.json();

      if (!response.ok || data?.status !== "success") {
        throw new Error(data?.message || t("mcpTools.service.healthFailed"));
      }

      const nextHealth = normalizeMcpHealthStatus(data?.data?.health_status);
      setDraftService({ ...draftService, healthStatus: nextHealth });
    } catch (error) {
      const messageText = error instanceof Error ? error.message : t("mcpTools.service.healthFailed");
      const displayMessage = messageText === "MCP connection failed" ? t("mcpTools.error.connectionFailed") : messageText;
      setLoadError(displayMessage);
      message.error(displayMessage);
    } finally {
      setHealthCheckLoading(false);
    }
  };

  const handleDeleteService = async (serviceName: string) => {
    try {
      const response = await fetch(`/api/mcp-tools/delete?name=${encodeURIComponent(serviceName)}`, {
        method: "DELETE",
        headers: getAuthHeaders(),
      });
      const data = await response.json();
      if (!response.ok || data?.status !== "success") {
        throw new Error(data?.message || t("mcpTools.service.deleteFailed"));
      }

      setServices((prev) => prev.filter((item) => item.name !== serviceName));
      setToolCache((prev) => {
        const next: Record<string, McpTool[]> = {};
        for (const [key, value] of Object.entries(prev)) {
          if (!key.startsWith(`${serviceName}@@`)) {
            next[key] = value;
          }
        }
        return next;
      });
      setSelectedService(null);
      message.success(t("mcpTools.service.deleted"));
    } catch (error) {
      const messageText = error instanceof Error ? error.message : t("mcpTools.service.deleteFailed");
      message.error(messageText);
    }
  };

  const filteredServices = useMemo(() => {
    const keyword = searchValue.trim().toLowerCase();
    if (!keyword) return services;
    return services.filter((item) => {
      return (
        item.name.toLowerCase().includes(keyword) ||
        item.description.toLowerCase().includes(keyword) ||
        item.tags.some((tag) => tag.toLowerCase().includes(keyword))
      );
    });
  }, [searchValue, services]);

  const filteredMarketServices = marketServices;

  return (
    <div className="w-full min-h-full bg-slate-50">
      <div className="w-full max-w-6xl mx-auto px-6 py-10">
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <h1 className="text-3xl md:text-4xl font-semibold text-slate-900">
              {t("mcpTools.page.title")}
            </h1>
            <p className="text-slate-600 text-base">
              {t("mcpTools.page.subtitle")}
            </p>
          </div>

          <div className="flex flex-col md:flex-row gap-4 items-stretch">
            <div className="md:basis-2/3">
              <label className="sr-only" htmlFor="mcp-search">
                {t("mcpTools.page.searchLabel")}
              </label>
              <div className="relative">
                <Input
                  id="mcp-search"
                  value={searchValue}
                  onChange={(event) => setSearchValue(event.target.value)}
                  placeholder={t("mcpTools.page.searchPlaceholder")}
                  size="large"
                  className="w-full h-10 rounded-2xl"
                />
                <div className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-xs font-medium text-amber-700">
                  {t("mcpTools.page.resultCount", { count: filteredServices.length })}
                </div>
              </div>
            </div>
            <div className="md:basis-1/3">
              <Button
                type="primary"
                size="large"
                block
                onClick={() => {
                  setShowAddModal(true);
                  setAddModalTab(MCP_TAB.LOCAL);
                }}
                className="w-full h-10 rounded-full bg-gradient-to-r from-emerald-600 via-teal-600 to-cyan-600 px-6 text-white font-semibold shadow-lg shadow-emerald-200/50 transition hover:translate-y-[-1px] hover:shadow-emerald-300/70"
              >
                {t("mcpTools.page.addService")}
              </Button>
            </div>
          </div>

          {isLoading ? (
            <div className="rounded-3xl border border-dashed border-slate-200 bg-white/60 px-6 py-10 text-center text-slate-500">
              {t("mcpTools.page.loading")}
            </div>
          ) : filteredServices.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-slate-200 bg-white/60 px-6 py-10 text-center text-slate-500">
              {t("mcpTools.page.empty")}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              {filteredServices.map((service) => (
                <div
                  key={`${service.name}-${service.source}`}
                  onClick={() => setSelectedService(service)}
                  className="group rounded-3xl border border-slate-200/80 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <h3 className="truncate text-xl font-semibold text-slate-900" title={service.name}>
                        {service.name}
                      </h3>
                      <p
                        className="mt-2 line-clamp-2 break-all text-sm text-slate-600"
                        title={service.description}
                      >
                        {service.description}
                      </p>
                    </div>
                    <span
                      className={`shrink-0 whitespace-nowrap rounded-full px-3 py-1 text-xs font-semibold ${
                        service.status === MCP_SERVICE_STATUS.ENABLED
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {service.status === MCP_SERVICE_STATUS.ENABLED
                        ? t("mcpTools.status.enabled")
                        : t("mcpTools.status.disabled")}
                    </span>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <span className="rounded-full bg-amber-100 text-amber-700 px-2.5 py-1 text-xs font-medium">
                      {service.source === MCP_TAB.LOCAL
                        ? t("mcpTools.source.local")
                        : t("mcpTools.source.market")}
                    </span>
                    {service.tags.map((tag) => (
                      <span
                        key={`${service.name}-${tag}`}
                        className="rounded-full bg-sky-100 text-sky-700 px-2.5 py-1 text-xs font-medium"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>

                  <div className="mt-5 flex items-center justify-end text-xs text-slate-500">
                    <div className="flex items-center gap-2">
                      <Button
                        size="small"
                        className="rounded-full"
                        autoInsertSpace={false}
                        onClick={(event) => {
                          event.stopPropagation();
                          handleEnableToggle(service).catch(() => undefined);
                        }}
                      >
                        {service.status === MCP_SERVICE_STATUS.ENABLED
                          ? t("mcpTools.service.disable")
                          : t("mcpTools.service.enable")}
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <McpServiceDetailModal
        open={Boolean(selectedService && draftService)}
        selectedService={selectedService}
        draftService={draftService}
        tagDrafts={tagDrafts}
        tagInputValue={tagInputValue}
        healthCheckLoading={healthCheckLoading}
        loadingTools={loadingTools}
        onClose={() => setSelectedService(null)}
        onDraftServiceChange={setDraftService}
        onTagInputChange={setTagInputValue}
        onAddDetailTag={addDetailTag}
        onRemoveTag={(index) => setTagDrafts((prev) => prev.filter((_, idx) => idx !== index))}
        onHealthCheck={handleHealthCheck}
        onViewTools={handleViewTools}
        onDeleteConfirm={(serviceName) => {
          confirm({
            title: t("mcpTools.delete.confirmTitle"),
            content: (
              <div className="space-y-1">
                <p className="text-sm text-slate-600 break-all">{serviceName}</p>
                <p className="text-xs text-slate-400">{t("mcpTools.delete.confirmDesc")}</p>
              </div>
            ),
            danger: true,
            onOk: () => {
              handleDeleteService(serviceName).catch(() => undefined);
            },
          });
        }}
        onSaveUpdates={handleSaveUpdates}
        onToggleEnable={(service) => {
          handleEnableToggle(service).catch(() => undefined);
        }}
      />

      <AddMcpServiceModal
        open={showAddModal}
        addModalTab={addModalTab}
        marketSearchValue={marketSearchValue}
        selectedMarketService={selectedMarketService}
        filteredMarketServices={filteredMarketServices}
        marketLoading={marketLoading}
        marketPage={marketPage}
        hasPrevMarketPage={marketCursorHistory.length > 0}
        hasNextMarketPage={Boolean(marketNextCursor)}
        marketVersion={marketVersion}
        marketUpdatedSince={marketUpdatedSince}
        marketIncludeDeleted={marketIncludeDeleted}
        newServiceName={newServiceName}
        newServiceDesc={newServiceDesc}
        newServerType={newServerType}
        newServiceUrl={newServiceUrl}
        newServiceAuthorizationToken={newServiceAuthorizationToken}
        containerUploadFileList={containerUploadFileList}
        containerConfigJson={containerConfigJson}
        containerPort={containerPort}
        containerServiceName={containerServiceName}
        newTagDrafts={newTagDrafts}
        newTagInputValue={newTagInputValue}
        addingService={addingService}
        onClose={closeAddModal}
        onAddModalTabChange={setAddModalTab}
        onMarketSearchChange={setMarketSearchValue}
        onRefreshMarket={() => loadMarketFirstPage(marketSearchValue)}
        onPrevMarketPage={handleMarketPrevPage}
        onNextMarketPage={handleMarketNextPage}
        onMarketVersionChange={setMarketVersion}
        onMarketUpdatedSinceChange={setMarketUpdatedSince}
        onMarketIncludeDeletedChange={setMarketIncludeDeleted}
        onSelectMarketService={setSelectedMarketService}
        onQuickAddFromMarket={handleQuickAddFromMarket}
        onNewServiceNameChange={setNewServiceName}
        onNewServiceDescChange={setNewServiceDesc}
        onNewServerTypeChange={setNewServerType}
        onNewServiceUrlChange={setNewServiceUrl}
        onNewServiceAuthorizationTokenChange={setNewServiceAuthorizationToken}
        onContainerUploadFileListChange={setContainerUploadFileList}
        onContainerConfigJsonChange={setContainerConfigJson}
        onContainerPortChange={setContainerPort}
        onContainerServiceNameChange={setContainerServiceName}
        onAddNewTag={addNewTag}
        onRemoveNewTag={(index) => setNewTagDrafts((prev) => prev.filter((_, idx) => idx !== index))}
        onNewTagInputChange={setNewTagInputValue}
        onSaveAndAdd={handleAddService}
      />

      <McpToolListModal
        open={toolsModalVisible}
        onCancel={() => setToolsModalVisible(false)}
        loading={loadingTools}
        tools={currentServerTools}
        serverName={draftService?.name || t("mcpTools.service.defaultName")}
        onRefresh={handleRefreshTools}
      />

    </div>
  );
}