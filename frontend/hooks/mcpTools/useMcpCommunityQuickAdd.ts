"use client";

import { useCallback, useState } from "react";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  addContainerMcpToolService,
  addMcpToolService,
  incrementCommunityMcpDownloadCount,
  parseContainerMcpConfigJson,
} from "@/services/mcpToolsService";
import { checkContainerPortAvailable } from "./useContainerPortAvailability";
import { getMcpAddErrorMessage } from "@/lib/mcpTools";
import { McpSource, McpTransportType } from "@/const/mcpTools";
import { MCP_SERVERS_QUERY_KEY } from "@/hooks/mcp/useMcpServerList";
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
  containerPort: service.containerPort ?? undefined,
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
  const [nameError, setNameError] = useState<string | null>(null);

  const open = useCallback((service: CommunityMcpCard) => {
    setSource(service);
    setDraft(draftFromSource(service));
    setNameError(null);
  }, []);

  const close = useCallback(() => {
    setSource(null);
    setDraft(null);
    setNameError(null);
  }, []);

  const updateDraft = useCallback((patch: Partial<CommunityQuickAddDraft>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
    if (patch.name !== undefined) setNameError(null);
  }, []);

  /** Parse optional custom headers JSON, returning an error signal instead of throwing. */
  function tryParseCustomHeaders(raw: string | undefined): { value?: Record<string, string>; error?: true } {
    if (!raw?.trim()) return {};
    try {
      return { value: JSON.parse(raw.trim()) };
    } catch {
      return { error: true };
    }
  }

  function buildRegistryJson(): Record<string, unknown> {
    return {
      ...(draft!.registryJson || {}),
      ...(source!.authorDisplayName ? { _authorDisplayName: source!.authorDisplayName } : {}),
      ...(source!.authorName ? { _authorName: source!.authorName } : {}),
    };
  }

  async function submitMcpService(
    customHeaders: Record<string, string> | undefined,
    registryJson: Record<string, unknown>,
    asUrlFallback: boolean = false,
  ): Promise<boolean> {
    if (asUrlFallback) {
      // Community container MCP with unchanged default port —
      // the service is already running on that port; add as a URL reference
      // without starting a new container. Keep the container config for display.
      const serverUrl = `http://localhost:${draft!.containerPort}/mcp`;
      const containerConfig = draft!.containerConfigJson
        ? (JSON.parse(draft!.containerConfigJson) as Record<string, unknown>)
        : undefined;
      await addMcpToolService({
        name: draft!.name.trim(),
        description: draft!.description ?? "",
        source: McpSource.COMMUNITY,
        server_url: serverUrl,
        authorization_token: draft!.authorizationToken?.trim() || undefined,
        custom_headers: customHeaders,
        container_config: containerConfig,
        container_port: draft!.containerPort,
        tags: draft!.tags,
        version: draft!.version,
        registry_json: registryJson,
        market_id: source!.marketId,
        skip_health_check: true,
        enabled: true,
        group_ids: "",
      });
    } else if (draft!.transportType === McpTransportType.CONTAINER) {
      const mcpConfig = parseContainerMcpConfigJson(draft!.containerConfigJson ?? "");
      if (!mcpConfig) {
        message.error(t("mcpTools.add.error.containerJsonInvalid"));
        return false;
      }
      await addContainerMcpToolService({
        name: draft!.name.trim(),
        description: draft!.description ?? "",
        tags: draft!.tags,
        source: McpSource.COMMUNITY,
        authorization_token: draft!.authorizationToken?.trim() || undefined,
        registry_json: registryJson,
        market_id: source!.marketId,
        port: draft!.containerPort as number,
        mcp_config: mcpConfig,
      });
    } else {
      await addMcpToolService({
        name: draft!.name.trim(),
        description: draft!.description ?? "",
        source: McpSource.COMMUNITY,
        server_url: draft!.serverUrl.trim(),
        authorization_token: draft!.authorizationToken?.trim() || undefined,
        custom_headers: customHeaders,
        tags: draft!.tags,
        version: draft!.version,
        registry_json: registryJson,
        market_id: source!.marketId,
      });
    }
    return true;
  }

  function handleAddError(error: unknown) {
    message.error(getMcpAddErrorMessage(error, t));
  }

  const confirm = useCallback(async () => {
    if (!draft || !source) return;
    if (!draft.name.trim()) {
      message.warning(t("mcpTools.add.validate.nameRequired"));
      return;
    }

    // For a community container MCP whose port is unchanged (still the default),
    // the MCP service is assumed already running on that port — add as a URL
    // reference instead of starting a new container.
    const isDefaultPortCommunityMcp =
      draft.transportType === McpTransportType.CONTAINER &&
      source.marketId != null &&
      draft.containerPort != null &&
      draft.containerPort === source.containerPort;

    if (draft.transportType === McpTransportType.CONTAINER && !isDefaultPortCommunityMcp) {
      const available = await checkContainerPortAvailable(draft.containerPort);
      if (!available) {
        message.error(t("mcpTools.addModal.portOccupied", { port: draft.containerPort }));
        return;
      }
    }

    const parsedHeaders = tryParseCustomHeaders(draft.customHeaders);
    if (parsedHeaders.error) {
      message.error(t("mcpConfig.message.invalidCustomHeadersJson"));
      return;
    }

    const registryJson = buildRegistryJson();

    setSubmitting(true);
    try {
      const ok = await submitMcpService(parsedHeaders.value, registryJson, isDefaultPortCommunityMcp);
      if (!ok) return;

      message.success(t("mcpTools.add.success"));
      queryClient.invalidateQueries({ queryKey: MCP_TOOLS_QUERY_KEYS.services });
      queryClient.invalidateQueries({ queryKey: MCP_SERVERS_QUERY_KEY });
      await refreshToolListWithToast({ message, t, toastKey: "mcp-tools-refresh-tools-add-community" });

      if (source.marketId) {
        incrementCommunityMcpDownloadCount(source.marketId).catch((err) =>
          log.warn("[useMcpCommunityQuickAdd] Failed to increment download count", err)
        );
      }

      onSuccess();
      close();
    } catch (error) {
      log.error("[useMcpCommunityQuickAdd] Failed to add community service", { error });
      // If it's a name conflict, show inline in the modal so user can rename
      const errMsg = getMcpAddErrorMessage(error, t);
      const normalized = errMsg.toLowerCase();
      if (/已存在同名|name.*(exist|conflict)|already exists/.test(normalized)) {
        setNameError(errMsg);
      } else {
        message.error(errMsg);
      }
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
    nameError,
  };
}
