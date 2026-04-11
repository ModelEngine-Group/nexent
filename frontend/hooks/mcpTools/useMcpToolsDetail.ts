import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import log from "@/lib/logger";
import { MCP_HEALTH_STATUS } from "@/const/mcpTools";
import type { McpTool } from "@/types/agentConfig";
import { type McpServiceItem } from "@/types/mcpTools";
import {
  publishCommunityMcpTool,
  deleteMcpToolService,
  healthcheckMcpToolService,
  listMcpRuntimeTools,
  updateMcpToolService,
} from "@/services/mcpToolsService";

function isSameStringArray(left: string[] = [], right: string[] = []) {
  if (left.length !== right.length) return false;
  return left.every((item, index) => item === right[index]);
}

function extractBackendDetail(errorMessage: string): string {
  const raw = String(errorMessage || "");
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (parsed && typeof parsed.detail === "string") {
      return parsed.detail;
    }
  } catch {
    // Keep original text when it's not JSON.
  }
  return raw;
}

function extractHealthErrorMessage(detailText: string): string {
  const raw = String(detailText || "");
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw) as { message?: unknown };
    if (parsed && typeof parsed.message === "string") {
      return parsed.message;
    }
  } catch {
    // Keep original text when it's not JSON.
  }
  return raw;
}

function mapFixedHealthErrorMessage(rawMessage: string, t: (key: string) => string): string {
  if (rawMessage.includes("401")) {
    return t("mcpTools.service.health.http401");
  }
  if (rawMessage.includes("503")) {
    return t("mcpTools.service.health.http503");
  }
  return rawMessage;
}

type UseMcpToolsDetailParams = {
  selectedService: McpServiceItem | null;
  onSelectedServiceChange: (service: McpServiceItem | null) => void;
  onServicesReload: () => Promise<unknown>;
  onSyncToolNames: (service: Pick<McpServiceItem, "mcpId" | "name" | "serverUrl">, tools: McpTool[]) => void;
  t: (key: string) => string;
  message: MessageInstance;
};

export function useMcpToolsDetail({
  selectedService,
  onSelectedServiceChange,
  onServicesReload,
  onSyncToolNames,
  t,
  message,
}: UseMcpToolsDetailParams) {
  const queryClient = useQueryClient();
  const [draftService, setDraftService] = useState<McpServiceItem | null>(null);
  const [tagDrafts, setTagDrafts] = useState<string[]>([]);
  const [tagInputValue, setTagInputValue] = useState("");
  const [healthCheckLoading, setHealthCheckLoading] = useState(false);
  const [healthErrorModalVisible, setHealthErrorModalVisible] = useState(false);
  const [healthErrorModalTitle, setHealthErrorModalTitle] = useState("");
  const [healthErrorModalDetail, setHealthErrorModalDetail] = useState("");
  const [toolsModalVisible, setToolsModalVisible] = useState(false);
  const [currentServerTools, setCurrentServerTools] = useState<McpTool[]>([]);
  const previousSelectedServiceIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (selectedService) {
      const previousId = previousSelectedServiceIdRef.current;
      const isSameService = previousId === selectedService.mcpId;
      previousSelectedServiceIdRef.current = selectedService.mcpId;

      if (isSameService) {
        // Keep local editing/tool modal state when only metadata updates for the same service.
        setDraftService((prev) => {
          if (!prev) {
            return { ...selectedService };
          }
          return {
            ...prev,
            status: selectedService.status,
            healthStatus: selectedService.healthStatus,
            containerStatus: selectedService.containerStatus,
            updatedAt: selectedService.updatedAt,
            version: selectedService.version,
            registryJson: selectedService.registryJson,
            configJson: selectedService.configJson,
          };
        });
      } else {
        setDraftService({ ...selectedService });
        setTagDrafts(selectedService.tags);
        setTagInputValue("");
        setCurrentServerTools([]);
      }
      return;
    }

    previousSelectedServiceIdRef.current = null;
    setDraftService(null);
    setTagDrafts([]);
    setTagInputValue("");
    setCurrentServerTools([]);
    setToolsModalVisible(false);
  }, [selectedService]);

  const updateMutation = useMutation({ mutationFn: updateMcpToolService });
  const deleteMutation = useMutation({ mutationFn: deleteMcpToolService });
  const healthcheckMutation = useMutation({ mutationFn: healthcheckMcpToolService });
  const publishMutation = useMutation({ mutationFn: publishCommunityMcpTool });

  const toolsQueryKey = ["mcp-tools", "runtime-tools", draftService?.mcpId];

  const toolsQuery = useQuery<McpTool[]>({
    queryKey: toolsQueryKey,
    enabled: false,
    retry: false,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    queryFn: async () => {
      if (!draftService) {
        throw new Error(t("mcpTools.tools.loadFailed"));
      }
      const result = await listMcpRuntimeTools(draftService.mcpId);
      return result.data;
    },
  });

  useEffect(() => {
    if (!draftService || !toolsQuery.data) return;
    const nextToolNames = toolsQuery.data.map((item) => item.name);
    setCurrentServerTools((prev) => (isSameStringArray(prev.map((item) => item.name), nextToolNames) ? prev : toolsQuery.data));
    onSyncToolNames(
      { mcpId: draftService.mcpId, name: draftService.name, serverUrl: draftService.serverUrl },
      toolsQuery.data
    );
    setDraftService((prev) =>
      !prev || prev.mcpId !== draftService.mcpId
        ? prev
        : isSameStringArray(prev.tools, nextToolNames)
        ? prev
        : { ...prev, tools: nextToolNames }
    );
  }, [draftService?.mcpId, draftService?.name, draftService?.serverUrl, toolsQuery.data, onSyncToolNames]);

  const loadTools = async () => {
    if (!draftService) return;
    const result = await toolsQuery.refetch();
    if (result.error) {
      log.error("[useMcpToolsDetail] Failed to load runtime tools", {
        error: result.error,
        mcpId: draftService.mcpId,
      });
      message.error(t("mcpTools.tools.loadFailed"));
      return;
    }

    if (result.data && result.data.length === 0) {
      message.info(t("mcpConfig.toolsList.empty"));
    }
  };

  const handleViewTools = () => {
    if (!draftService) return;
    setToolsModalVisible(true);

    const cachedTools = queryClient.getQueryData<McpTool[]>(toolsQueryKey);
    if (cachedTools && cachedTools.length > 0) {
      setCurrentServerTools(cachedTools);
      return;
    }

    loadTools().catch(() => undefined);
  };

  const handleRefreshTools = () => {
    if (!draftService) return;
    loadTools().catch(() => undefined);
  };

  const handleSaveUpdates = async () => {
    if (!selectedService || !draftService) return;
    const nextTags = tagDrafts.map((tag) => tag.trim()).filter((tag) => tag.length > 0);
    try {
      const result = await updateMutation.mutateAsync({
        mcp_id: selectedService.mcpId,
        name: draftService.name,
        description: draftService.description,
        server_url: draftService.serverUrl,
        authorization_token: draftService.authorizationToken ?? "",
        tags: nextTags,
      });
      const updatedService = { ...draftService, tags: nextTags };
      await onServicesReload();
      onSelectedServiceChange(updatedService);
      setDraftService(updatedService);
      setTagDrafts(nextTags);
      message.success(t("mcpTools.service.saveSuccess"));
    } catch (error) {
      log.error("[useMcpToolsDetail] Failed to save service updates", {
        error,
        selectedServiceName: selectedService.name,
        selectedServiceId: selectedService.mcpId,
        selectedServiceUrl: selectedService.serverUrl,
        draftServiceName: draftService.name,
        draftServiceId: draftService.mcpId,
        draftServiceUrl: draftService.serverUrl,
      });
      message.error(t("mcpTools.service.saveFailed"));
    }
  };

  const handleHealthCheck = async () => {
    if (!draftService) return;
    setHealthCheckLoading(true);
    try {
      const result = await healthcheckMutation.mutateAsync({
        mcp_id: draftService.mcpId,
      });
      if (!result.data) throw new Error(t("mcpTools.service.healthFailed"));
      setDraftService({ ...draftService, healthStatus: result.data.health_status });
      setHealthErrorModalVisible(false);
      setHealthErrorModalTitle("");
      setHealthErrorModalDetail("");
    } catch (error) {
      setDraftService((prev) => (prev ? { ...prev, healthStatus: MCP_HEALTH_STATUS.UNHEALTHY } : prev));
      log.error("[useMcpToolsDetail] Failed to run health check", {
        error,
        serviceId: draftService.mcpId,
        serviceName: draftService.name,
        serverUrl: draftService.serverUrl,
      });
      const rawErrorText = error instanceof Error ? String(error.message || "") : "";
      const backendDetail = extractBackendDetail(rawErrorText);
      const extractedMessage = extractHealthErrorMessage(backendDetail);
      const normalizedErrorText = mapFixedHealthErrorMessage(
        extractedMessage || t("mcpTools.service.healthFailed"),
        t
      );
      const isTimeout = normalizedErrorText === "MCP_HEALTH_TIMEOUT";
      setHealthErrorModalTitle(
        isTimeout ? t("mcpTools.service.healthTimeoutTitle") : t("mcpTools.service.healthErrorTitle")
      );
      setHealthErrorModalDetail(
        isTimeout ? t("mcpTools.service.healthTimeoutMessage") : normalizedErrorText
      );
      setHealthErrorModalVisible(true);
    } finally {
      setHealthCheckLoading(false);
    }
  };

  const onDeleteService = async (mcpId: number, serviceName: string) => {
    try {
      await deleteMutation.mutateAsync(mcpId);
      await onServicesReload();
      onSelectedServiceChange(null);
      message.success(t("mcpTools.service.deleted"));
    } catch (error) {
      log.error("[useMcpToolsDetail] Failed to delete service", {
        error,
        serviceId: mcpId,
        serviceName,
      });
      message.error(t("mcpTools.service.deleteFailed"));
    }
  };

  const handlePublishToCommunity = async () => {
    if (!selectedService) return;
    try {
      await publishMutation.mutateAsync(selectedService.mcpId);
      message.success(t("mcpTools.community.publishSuccess"));
    } catch (error) {
      log.error("[useMcpToolsDetail] Failed to publish service to community", {
        error,
        serviceId: selectedService.mcpId,
        serviceName: selectedService.name,
      });
      message.error(t("mcpTools.community.publishFailed"));
    }
  };

  const addDetailTag = () => {
    const nextTag = tagInputValue.trim();
    if (!nextTag) return;
    setTagDrafts((prev) => (prev.includes(nextTag) ? prev : [...prev, nextTag]));
    setTagInputValue("");
  };

  return {
    selectedService,
    draftService,
    tagDrafts,
    tagInputValue,
    healthCheckLoading,
    healthErrorModalVisible,
    healthErrorModalTitle,
    healthErrorModalDetail,
    loadingTools: toolsQuery.isFetching,
    toolsModalVisible,
    currentServerTools,
    setDraftService,
    setTagInputValue,
    addDetailTag,
    removeTag: (index: number) => setTagDrafts((prev) => prev.filter((_, idx) => idx !== index)),
    handleHealthCheck,
    handleViewTools,
    handleSaveUpdates,
    closeToolsModal: () => setToolsModalVisible(false),
    handleRefreshTools,
    closeHealthErrorModal: () => setHealthErrorModalVisible(false),
    onDeleteService,
    handlePublishToCommunity,
    publishLoading: publishMutation.isPending,
    closeDetail: () => onSelectedServiceChange(null),
  };
}
