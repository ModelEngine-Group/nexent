"use client";

import { useCallback, useState } from "react";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  addContainerMcpToolService,
  addMcpToolService,
  parseContainerMcpConfigJson,
} from "@/services/mcpToolsService";
import { checkContainerPortAvailable } from "./useContainerPortAvailability";
import { McpSource, McpTransportType } from "@/const/mcpTools";
import type { CommunityMcpCard, CommunityQuickAddDraft } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";
import { refreshToolListWithToast } from "./useRefreshToolListWithToast";

interface UseMcpCommunityQuickAddParams {
  onSuccess: () => void;
}

const draftFromSource = (
  service: CommunityMcpCard
): CommunityQuickAddDraft => ({
  name: service.name || "",
  description: service.description || "",
  transportType:
    service.transportType === McpTransportType.CONTAINER ? McpTransportType.CONTAINER : McpTransportType.URL,
  serverUrl: service.serverUrl || "",
  authorizationToken: "",
  customHeaders: "",
  containerConfigJson: service.configJson ? JSON.stringify(service.configJson, null, 2) : "",
  containerPort: undefined,
  tags: service.tags || [],
  version: service.version || undefined,
  registryJson: service.registryJson,
});

/**
 * Confirmation modal state + submission flow for adding a community MCP into
 * the local workspace.
 */
export function useMcpCommunityQuickAdd({
  onSuccess,
}: UseMcpCommunityQuickAddParams) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  const [source, setSource] = useState<CommunityMcpCard | null>(null);
  const [draft, setDraft] = useState<CommunityQuickAddDraft | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const open = useCallback((service: CommunityMcpCard) => {
    setSource(service);
    setDraft(draftFromSource(service));
  }, []);

  const close = useCallback(() => {
    setSource(null);
    setDraft(null);
  }, []);

  const updateDraft = useCallback((patch: Partial<CommunityQuickAddDraft>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const confirm = useCallback(async () => {
    if (!draft || !source) return;
    const name = draft.name.trim();
    if (!name) {
      message.warning(t("mcpTools.add.validate.nameRequired"));
      return;
    }

    const isContainer = draft.transportType === McpTransportType.CONTAINER;
    if (isContainer) {
      const available = await checkContainerPortAvailable(draft.containerPort);
      if (!available) {
        message.error(
          t("mcpTools.addModal.portOccupied", { port: draft.containerPort })
        );
        return;
      }
    }

    // Parse custom headers JSON if provided
    let customHeaders: Record<string, string> | undefined;
    if (draft.customHeaders?.trim()) {
      try {
        customHeaders = JSON.parse(draft.customHeaders.trim());
      } catch {
        message.error(t("mcpConfig.message.invalidCustomHeadersJson"));
        return;
      }
    }

    setSubmitting(true);
    try {
      if (isContainer) {
        const mcpConfig = parseContainerMcpConfigJson(
          draft.containerConfigJson ?? ""
        );
        if (!mcpConfig) {
          message.error(t("mcpTools.add.error.containerJsonInvalid"));
          return;
        }
        await addContainerMcpToolService({
          name,
          description: draft.description ?? "",
          tags: draft.tags,
          source: McpSource.COMMUNITY,
          authorization_token: draft.authorizationToken?.trim() || undefined,
          registry_json: draft.registryJson,
          port: draft.containerPort as number,
          mcp_config: mcpConfig,
        });
      } else {
        await addMcpToolService({
          name,
          description: draft.description ?? "",
          source: McpSource.COMMUNITY,
          server_url: draft.serverUrl.trim(),
          authorization_token: draft.authorizationToken?.trim() || undefined,
          custom_headers: customHeaders,
          tags: draft.tags,
          version: draft.version,
          registry_json: draft.registryJson,
        });
      }

      message.success(t("mcpTools.add.success"));
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.services,
      });
      await refreshToolListWithToast({
        message,
        t,
        toastKey: "mcp-tools-refresh-tools-add-community",
      });
      onSuccess();
      close();
    } catch (error) {
      log.error("[useMcpCommunityQuickAdd] Failed to add community service", {
        error,
      });
      message.error(t("mcpTools.add.failed"));
    } finally {
      setSubmitting(false);
    }
  }, [close, draft, message, onSuccess, queryClient, source, t]);

  return {
    visible: Boolean(source),
    source,
    draft,
    updateDraft,
    open,
    close,
    confirm,
    submitting,
  };
}
