import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import log from "@/lib/logger";
import { MCP_HEALTH_STATUS } from "@/const/mcpTools";
import type { McpTool } from "@/types/agentConfig";
import {
  type McpServiceDetailActions,
  type McpServiceDetailState,
  type McpServiceItem,
} from "@/types/mcpTools";
import {
  deleteMcpToolService,
  healthcheckMcpToolService,
  listMcpRuntimeTools,
  updateMcpToolService,
} from "@/services/mcpToolsService";

function isSameStringArray(left: string[] = [], right: string[] = []) {
  if (left.length !== right.length) return false;
  return left.every((item, index) => item === right[index]);
}

type UseMcpToolsDetailParams = {
  selectedService: McpServiceItem | null;
  onSelectedServiceChange: (service: McpServiceItem | null) => void;
  onServicesReload: () => Promise<unknown>;
  onSyncToolNames: (service: Pick<McpServiceItem, "name" | "serverUrl">, tools: McpTool[]) => void;
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
  const [toolsModalVisible, setToolsModalVisible] = useState(false);
  const [currentServerTools, setCurrentServerTools] = useState<McpTool[]>([]);

  useEffect(() => {
    if (selectedService) {
      setDraftService({ ...selectedService });
      setTagDrafts(selectedService.tags);
      setTagInputValue("");
      setCurrentServerTools([]);
      return;
    }

    setDraftService(null);
    setTagDrafts([]);
    setTagInputValue("");
    setCurrentServerTools([]);
    setToolsModalVisible(false);
  }, [selectedService?.name, selectedService?.serverUrl]);

  const updateMutation = useMutation({ mutationFn: updateMcpToolService });
  const deleteMutation = useMutation({ mutationFn: deleteMcpToolService });
  const healthcheckMutation = useMutation({ mutationFn: healthcheckMcpToolService });

  const toolsQueryKey = ["mcp-tools", "runtime-tools", draftService?.name, draftService?.serverUrl];

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
      const result = await listMcpRuntimeTools(draftService.name, draftService.serverUrl);
      if (!result.success) {
        throw new Error(result.message || t("mcpTools.tools.loadFailed"));
      }
      return result.data;
    },
  });

  useEffect(() => {
    if (!draftService || !toolsQuery.data) return;
    const nextToolNames = toolsQuery.data.map((item) => item.name);
    setCurrentServerTools((prev) => (isSameStringArray(prev.map((item) => item.name), nextToolNames) ? prev : toolsQuery.data));
    onSyncToolNames(
      { name: draftService.name, serverUrl: draftService.serverUrl },
      toolsQuery.data
    );
    setDraftService((prev) =>
      !prev || prev.name !== draftService.name || prev.serverUrl !== draftService.serverUrl
        ? prev
        : isSameStringArray(prev.tools, nextToolNames)
        ? prev
        : { ...prev, tools: nextToolNames }
    );
  }, [draftService?.name, draftService?.serverUrl, toolsQuery.data, onSyncToolNames]);

  const loadTools = async () => {
    if (!draftService) return;
    const result = await toolsQuery.refetch();
    if (result.error) {
      log.error("[useMcpToolsDetail] Failed to load runtime tools", {
        error: result.error,
        serviceName: draftService.name,
        serverUrl: draftService.serverUrl,
      });
      const msg = result.error instanceof Error ? result.error.message : t("mcpTools.tools.loadFailed");
      message.error(msg);
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
        current_name: selectedService.name,
        name: draftService.name,
        description: draftService.description,
        server_url: draftService.serverUrl,
        authorization_token: draftService.authorizationToken ?? "",
        tags: nextTags,
      });
      if (!result.success) throw new Error(result.message || t("mcpTools.service.saveFailed"));
      const updatedService = { ...draftService, tags: nextTags };
      await onServicesReload();
      onSelectedServiceChange(updatedService);
      setDraftService(updatedService);
      setTagDrafts(nextTags);
      message.success(t("mcpTools.service.saveSuccess"));
    } catch (error) {
      const msg = error instanceof Error ? error.message : t("mcpTools.service.saveFailed");
      log.error("[useMcpToolsDetail] Failed to save service updates", {
        error,
        selectedServiceName: selectedService.name,
        selectedServiceUrl: selectedService.serverUrl,
        draftServiceName: draftService.name,
        draftServiceUrl: draftService.serverUrl,
      });
      message.error(msg === "MCP connection failed" ? t("mcpTools.error.connectionFailed") : msg);
    }
  };

  const handleHealthCheck = async () => {
    if (!draftService) return;
    setHealthCheckLoading(true);
    try {
      const result = await healthcheckMutation.mutateAsync({
        name: draftService.name,
        server_url: draftService.serverUrl,
      });
      if (!result.success || !result.data) throw new Error(result.message || t("mcpTools.service.healthFailed"));
      setDraftService({ ...draftService, healthStatus: result.data.health_status });
    } catch (error) {
      setDraftService((prev) => (prev ? { ...prev, healthStatus: MCP_HEALTH_STATUS.UNHEALTHY } : prev));
      const msg = error instanceof Error ? error.message : t("mcpTools.service.healthFailed");
      log.error("[useMcpToolsDetail] Failed to run health check", {
        error,
        serviceName: draftService.name,
        serverUrl: draftService.serverUrl,
      });
      message.error(msg === "MCP connection failed" ? t("mcpTools.error.connectionFailed") : msg);
    } finally {
      setHealthCheckLoading(false);
    }
  };

  const onDeleteService = async (serviceName: string) => {
    try {
      const result = await deleteMutation.mutateAsync(serviceName);
      if (!result.success) throw new Error(result.message || t("mcpTools.service.deleteFailed"));
      await onServicesReload();
      onSelectedServiceChange(null);
      message.success(t("mcpTools.service.deleted"));
    } catch (error) {
      log.error("[useMcpToolsDetail] Failed to delete service", {
        error,
        serviceName,
      });
      message.error(error instanceof Error ? error.message : t("mcpTools.service.deleteFailed"));
    }
  };

  const addDetailTag = () => {
    const nextTag = tagInputValue.trim();
    if (!nextTag) return;
    setTagDrafts((prev) => (prev.includes(nextTag) ? prev : [...prev, nextTag]));
    setTagInputValue("");
  };

  const state: McpServiceDetailState = {
    selectedService,
    draftService,
    tagDrafts,
    tagInputValue,
    healthCheckLoading,
    loadingTools: toolsQuery.isFetching,
    toolsModalVisible,
    currentServerTools,
  };

  const actions: McpServiceDetailActions & {
    onDeleteService: (serviceName: string) => Promise<void>;
    onCloseDetail: () => void;
  } = {
    onDraftServiceChange: setDraftService,
    onTagInputChange: setTagInputValue,
    onAddDetailTag: addDetailTag,
    onRemoveTag: (index: number) => setTagDrafts((prev) => prev.filter((_, idx) => idx !== index)),
    onHealthCheck: handleHealthCheck,
    onViewTools: handleViewTools,
    onSaveUpdates: handleSaveUpdates,
    onCloseToolsModal: () => setToolsModalVisible(false),
    onRefreshTools: handleRefreshTools,
    onDeleteService,
    onCloseDetail: () => onSelectedServiceChange(null),
  };

  return {
    state,
    actions,
  };
}
