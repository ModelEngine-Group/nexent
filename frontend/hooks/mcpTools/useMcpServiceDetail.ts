"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  deleteMcpToolService,
  healthcheckMcpToolService,
  listMcpRuntimeTools,
  publishCommunityMcpTool,
  updateMcpToolService,
} from "@/services/mcpToolsService";
import { updateToolList } from "@/services/mcpService";
import {
  isHttpUrl,
  isSameStringArray,
  parseHealthCheckError,
} from "@/lib/mcpTools";
import { MCP_HEALTH_STATUS, MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import type { McpTool } from "@/types/agentConfig";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

interface HealthErrorState {
  visible: boolean;
  title: string;
  detail: string;
}

interface ToolsModalState {
  visible: boolean;
  tools: McpTool[];
}

interface UseMcpServiceDetailParams {
  selectedService: McpServiceItem | null;
  onClose: () => void;
}

/**
 * Encapsulates all state and side effects required by the service detail modal.
 * The modal becomes a presentation component that just renders what this hook
 * returns.
 */
export function useMcpServiceDetail({
  selectedService,
  onClose,
}: UseMcpServiceDetailParams) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  const [draft, setDraft] = useState<McpServiceItem | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [healthChecking, setHealthChecking] = useState(false);
  const [healthError, setHealthError] = useState<HealthErrorState>({
    visible: false,
    title: "",
    detail: "",
  });
  const [toolsState, setToolsState] = useState<ToolsModalState>({
    visible: false,
    tools: [],
  });
  const [loadingTools, setLoadingTools] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    setDraft(selectedService ? { ...selectedService } : null);
    setTagInput("");
  }, [selectedService]);

  const invalidateServices = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: MCP_TOOLS_QUERY_KEYS.services });
    queryClient.invalidateQueries({ queryKey: MCP_TOOLS_QUERY_KEYS.tagStats });
  }, [queryClient]);

  const addTag = useCallback(() => {
    setDraft((prev) => {
      if (!prev) return prev;
      const next = tagInput.trim();
      if (!next || prev.tags.includes(next)) {
        setTagInput("");
        return prev;
      }
      setTagInput("");
      return { ...prev, tags: [...prev.tags, next] };
    });
  }, [tagInput]);

  const removeTag = useCallback((index: number) => {
    setDraft((prev) =>
      prev ? { ...prev, tags: prev.tags.filter((_, i) => i !== index) } : prev
    );
  }, []);

  const runHealthCheck = useCallback(async () => {
    if (!draft || draft.mcpId < 0) return;
    setHealthChecking(true);
    try {
      const result = await healthcheckMcpToolService({ mcp_id: draft.mcpId });
      const nextStatus =
        result.data?.health_status ?? MCP_HEALTH_STATUS.UNCHECKED;
      setDraft((prev) => (prev ? { ...prev, healthStatus: nextStatus } : prev));
      message.success(t("mcpTools.service.healthOk"));
      invalidateServices();
    } catch (error) {
      log.error("[useMcpServiceDetail] Health check failed", { error });
      const { title, detail } = parseHealthCheckError(error, (key) =>
        String(t(key))
      );
      setHealthError({ visible: true, title, detail });
      setDraft((prev) =>
        prev ? { ...prev, healthStatus: MCP_HEALTH_STATUS.UNHEALTHY } : prev
      );
    } finally {
      setHealthChecking(false);
    }
  }, [draft, invalidateServices, message, t]);

  const loadTools = useCallback(async () => {
    if (!draft || draft.mcpId < 0) return;
    setLoadingTools(true);
    try {
      const result = await listMcpRuntimeTools(draft.mcpId);
      setToolsState({ visible: true, tools: result.data || [] });
    } catch (error) {
      log.error("[useMcpServiceDetail] Failed to load tools", { error });
      message.error(t("mcpTools.service.loadToolsFailed"));
    } finally {
      setLoadingTools(false);
    }
  }, [draft, message, t]);

  const refreshTools = useCallback(async () => {
    if (!draft || draft.mcpId < 0) return;
    setLoadingTools(true);
    try {
      const result = await listMcpRuntimeTools(draft.mcpId);
      setToolsState((prev) => ({ ...prev, tools: result.data || [] }));
    } catch (error) {
      log.error("[useMcpServiceDetail] Failed to refresh tools", { error });
      message.error(t("mcpTools.service.loadToolsFailed"));
    } finally {
      setLoadingTools(false);
    }
  }, [draft, message, t]);

  const closeToolsModal = useCallback(() => {
    setToolsState({ visible: false, tools: [] });
  }, []);

  const closeHealthError = useCallback(() => {
    setHealthError({ visible: false, title: "", detail: "" });
  }, []);

  const hasUnsavedChanges = useMemo(() => {
    if (!draft || !selectedService) return false;
    return (
      draft.name.trim() !== selectedService.name ||
      draft.description !== selectedService.description ||
      draft.serverUrl.trim() !== selectedService.serverUrl ||
      !isSameStringArray(draft.tags, selectedService.tags) ||
      (draft.authorizationToken ?? "") !==
        (selectedService.authorizationToken ?? "")
    );
  }, [draft, selectedService]);

  const save = useCallback(async () => {
    if (!draft || !selectedService) return;
    const nextName = draft.name.trim();
    const nextUrl = draft.serverUrl.trim();
    const nextToken = (draft.authorizationToken ?? "").trim();
    const nextTags = draft.tags;

    if (!nextName) {
      message.warning(t("mcpTools.add.validate.nameRequired"));
      return;
    }
    if (
      (draft.transportType === MCP_TRANSPORT_TYPE.HTTP ||
        draft.transportType === MCP_TRANSPORT_TYPE.SSE) &&
      !isHttpUrl(nextUrl)
    ) {
      message.warning(t("mcpTools.add.validate.httpUrlFormat"));
      return;
    }

    setSaving(true);
    try {
      await updateMcpToolService({
        mcp_id: draft.mcpId,
        name: nextName,
        description: draft.description,
        server_url: nextUrl,
        tags: nextTags,
        authorization_token: nextToken || undefined,
      });
      message.success(t("mcpTools.service.updated"));
      invalidateServices();
      try {
        await updateToolList();
      } catch (error) {
        log.error("[useMcpServiceDetail] Failed to refresh tool list", {
          error,
        });
      }
    } catch (error) {
      log.error("[useMcpServiceDetail] Failed to save service", { error });
      message.error(t("mcpTools.service.updateFailed"));
    } finally {
      setSaving(false);
    }
  }, [draft, invalidateServices, message, selectedService, t]);

  const remove = useCallback(async () => {
    if (!selectedService || selectedService.mcpId < 0) return;
    setDeleting(true);
    try {
      await deleteMcpToolService(selectedService.mcpId);
      message.success(t("mcpTools.service.deleted"));
      invalidateServices();
      try {
        await updateToolList();
      } catch (error) {
        log.error(
          "[useMcpServiceDetail] Failed to refresh tool list after delete",
          { error }
        );
      }
      onClose();
    } catch (error) {
      log.error("[useMcpServiceDetail] Failed to delete service", { error });
      message.error(t("mcpTools.service.deleteFailed"));
    } finally {
      setDeleting(false);
    }
  }, [invalidateServices, message, onClose, selectedService, t]);

  const publish = useCallback(async () => {
    if (!selectedService || selectedService.mcpId < 0) return;
    setPublishing(true);
    try {
      await publishCommunityMcpTool(selectedService.mcpId);
      message.success(t("mcpTools.community.publishSuccess"));
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.myCommunity,
      });
    } catch (error) {
      log.error("[useMcpServiceDetail] Publish failed", { error });
      message.error(t("mcpTools.community.publishFailed"));
    } finally {
      setPublishing(false);
    }
  }, [message, queryClient, selectedService, t]);

  return {
    draft,
    setDraft,
    tagInput,
    setTagInput,
    addTag,
    removeTag,
    hasUnsavedChanges,
    healthChecking,
    runHealthCheck,
    healthError,
    closeHealthError,
    toolsState,
    loadingTools,
    loadTools,
    refreshTools,
    closeToolsModal,
    publishing,
    publish,
    saving,
    save,
    deleting,
    remove,
  };
}
