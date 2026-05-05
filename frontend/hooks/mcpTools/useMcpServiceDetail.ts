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
  parseContainerMcpConfigJson,
  publishCommunityMcpTool,
  updateMcpToolService,
} from "@/services/mcpToolsService";
import { refreshToolListWithToast } from "./refreshToolListWithToast";
import { isHttpUrl, isSameStringArray } from "@/lib/mcpTools";
import { McpHealthStatus, McpTransportType } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import type { McpTool } from "@/types/agentConfig";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

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
  const [healthChecking, setHealthChecking] = useState(false);
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
  }, [selectedService]);

  const invalidateServices = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: MCP_TOOLS_QUERY_KEYS.services });
    queryClient.invalidateQueries({ queryKey: MCP_TOOLS_QUERY_KEYS.tagStats });
  }, [queryClient]);

  const addTag = useCallback((tag: string) => {
    const next = tag.trim();
    if (!next) return;
    setDraft((prev) => {
      if (!prev || prev.tags.includes(next)) return prev;
      return { ...prev, tags: [...prev.tags, next] };
    });
  }, []);

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
        result.data?.health_status ?? McpHealthStatus.UNCHECKED;
      setDraft((prev) => (prev ? { ...prev, healthStatus: nextStatus } : prev));
      message.success(t("mcpTools.service.healthOk"));
      invalidateServices();
    } catch (error) {
      log.error("[useMcpServiceDetail] Health check failed", { error });
      message.error(t("mcpTools.service.healthFailed"));
      setDraft((prev) =>
        prev ? { ...prev, healthStatus: McpHealthStatus.UNHEALTHY } : prev
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
      message.error(t("mcpTools.tools.loadFailed"));
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
      message.error(t("mcpTools.tools.loadFailed"));
    } finally {
      setLoadingTools(false);
    }
  }, [draft, message, t]);

  const closeToolsModal = useCallback(() => {
    setToolsState({ visible: false, tools: [] });
  }, []);

  const hasUnsavedChanges = useMemo(() => {
    if (!draft || !selectedService) return false;
    return (
      draft.name.trim() !== selectedService.name ||
      draft.description !== selectedService.description ||
      draft.serverUrl.trim() !== selectedService.serverUrl ||
      !isSameStringArray(draft.tags, selectedService.tags) ||
      (draft.authorizationToken ?? "") !==
        (selectedService.authorizationToken ?? "") ||
      (draft.version ?? "") !== (selectedService.version ?? "")
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
    if (draft.transportType === McpTransportType.URL && !isHttpUrl(nextUrl)
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
      message.success(t("mcpTools.service.saveSuccess"));
      invalidateServices();
      await refreshToolListWithToast({
        message,
        t,
        toastKey: "mcp-tools-refresh-tools-save",
      });
    } catch (error) {
      log.error("[useMcpServiceDetail] Failed to save service", { error });
      message.error(t("mcpTools.service.saveFailed"));
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
      await refreshToolListWithToast({
        message,
        t,
        toastKey: "mcp-tools-refresh-tools-delete",
      });
      onClose();
    } catch (error) {
      log.error("[useMcpServiceDetail] Failed to delete service", { error });
      message.error(t("mcpTools.service.deleteFailed"));
    } finally {
      setDeleting(false);
    }
  }, [invalidateServices, message, onClose, selectedService, t]);

  /**
   * Publishes the current service to the community. Optional modal fields
   * override the snapshot stored on the new community row; the original MCP row
   * is never mutated.
   */
  const publish = useCallback(
    async (override?: {
      name?: string;
      description?: string;
      version?: string;
      tags?: string[];
      serverUrl?: string;
      containerConfigJson?: string;
    }) => {
      if (!selectedService || selectedService.mcpId < 0) return false;
      setPublishing(true);
      try {
        const isContainer =
          selectedService.transportType === McpTransportType.CONTAINER;
        const editedConfigText = isContainer
          ? (override?.containerConfigJson ?? "").trim()
          : "";
        const parsedConfig = isContainer
          ? parseContainerMcpConfigJson(editedConfigText)
          : null;
        if (isContainer && !parsedConfig) {
          message.error(t("mcpTools.add.error.containerJsonInvalid"));
          return false;
        }

        const sourceName = (selectedService.name || "").trim();
        const sourceDesc = selectedService.description || "";
        const sourceVersion = (selectedService.version ?? "").trim();
        const editedName = (override?.name ?? sourceName).trim();
        const editedDesc = override?.description ?? sourceDesc;
        const editedVersion = (override?.version ?? sourceVersion).trim();
        const editedTags = override?.tags ?? selectedService.tags ?? [];
        const editedServerUrl = (
          override?.serverUrl ?? selectedService.serverUrl ?? ""
        ).trim();

        await publishCommunityMcpTool({
          mcp_id: selectedService.mcpId,
          name: editedName,
          description: editedDesc,
          version: editedVersion,
          tags: editedTags,
          ...(!isContainer ? { mcp_server: editedServerUrl } : {}),
          ...(parsedConfig ? { config_json: parsedConfig } : {}),
        });

        message.success(t("mcpTools.community.publishSuccess"));
        queryClient.invalidateQueries({
          queryKey: MCP_TOOLS_QUERY_KEYS.myCommunity,
        });
        return true;
      } catch (error) {
        log.error("[useMcpServiceDetail] Publish failed", { error });
        message.error(t("mcpTools.community.publishFailed"));
        return false;
      } finally {
        setPublishing(false);
      }
    },
    [message, queryClient, selectedService, t]
  );

  return {
    draft,
    setDraft,
    addTag,
    removeTag,
    hasUnsavedChanges,
    healthChecking,
    runHealthCheck,
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
