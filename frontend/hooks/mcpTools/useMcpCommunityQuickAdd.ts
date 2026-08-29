"use client";

import { useCallback, useState } from "react";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  addContainerMcpToolServiceStream,
  addMcpToolService,
  incrementCommunityMcpDownloadCount,
  parseContainerMcpConfigJson,
} from "@/services/mcpToolsService";
import { checkContainerPortAvailable } from "./useContainerPortAvailability";
import { getMcpAddErrorMessage } from "@/lib/mcpTools";
import { McpSource, McpTransportType } from "@/const/mcpTools";
import { MCP_SERVERS_QUERY_KEY } from "@/hooks/mcp/useMcpServerList";
import type {
  CommunityMcpCard,
  CommunityQuickAddDraft,
} from "@/types/mcpTools";
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
    service.transportType === McpTransportType.CONTAINER
      ? McpTransportType.CONTAINER
      : McpTransportType.URL,
  serverUrl: service.serverUrl || "",
  authorizationToken: service.sharedFields?.authorizationToken
    ? service.authorizationToken || ""
    : "",
  customHeaders: service.sharedFields?.customHeaders
    ? typeof service.customHeaders === "string"
      ? service.customHeaders
      : JSON.stringify(service.customHeaders || {}, null, 2)
    : "",
  containerConfigJson: service.configJson
    ? JSON.stringify(service.configJson, null, 2)
    : "",
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
  const [deploymentStarted, setDeploymentStarted] = useState(false);
  const [containerId, setContainerId] = useState<string | null>(null);

  const open = useCallback((service: CommunityMcpCard) => {
    setSource(service);
    setDraft(draftFromSource(service));
    setNameError(null);
    setDeploymentStarted(false);
    setContainerId(null);
  }, []);

  const close = useCallback(() => {
    setSource(null);
    setDraft(null);
    setNameError(null);
    setDeploymentStarted(false);
    setContainerId(null);
  }, []);

  const updateDraft = useCallback((patch: Partial<CommunityQuickAddDraft>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
    if (patch.name !== undefined) setNameError(null);
  }, []);

  /** Parse optional custom headers JSON, returning an error signal instead of throwing. */
  function tryParseCustomHeaders(raw: string | undefined): {
    value?: Record<string, string>;
    error?: true;
  } {
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
      ...(source!.authorDisplayName
        ? { _authorDisplayName: source!.authorDisplayName }
        : {}),
      ...(source!.authorName ? { _authorName: source!.authorName } : {}),
    };
  }

  async function submitMcpService(
    customHeaders: Record<string, string> | undefined,
    registryJson: Record<string, unknown>
  ): Promise<false> {
    if (draft!.transportType === McpTransportType.CONTAINER) {
      const mcpConfig = parseContainerMcpConfigJson(
        draft!.containerConfigJson ?? ""
      );
      if (!mcpConfig) {
        message.error(t("mcpTools.add.error.containerJsonInvalid"));
        return false;
      }
      await addContainerMcpToolServiceStream(
        {
          name: draft!.name.trim(),
          description: draft!.description ?? "",
          tags: draft!.tags,
          source: McpSource.COMMUNITY,
          authorization_token: draft!.authorizationToken?.trim() || undefined,
          registry_json: registryJson,
          market_id: source!.marketId,
          port: draft!.containerPort as number,
          mcp_config: mcpConfig,
        },
        (result) => {
          if (result.container_id) setContainerId(result.container_id);
        }
      );
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
    return false;
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

    const isContainerDeployment =
      draft.transportType === McpTransportType.CONTAINER;
    if (isContainerDeployment) {
      setDeploymentStarted(true);
      setContainerId(null);
    }
    setSubmitting(true);
    try {
      if (isContainerDeployment) {
        const available = await checkContainerPortAvailable(
          draft.containerPort
        );
        if (!available) {
          message.error(
            t("mcpTools.addModal.portOccupied", { port: draft.containerPort })
          );
          return;
        }
      }

      const parsedHeaders = tryParseCustomHeaders(draft.customHeaders);
      if (parsedHeaders.error) {
        message.error(t("mcpConfig.message.invalidCustomHeadersJson"));
        return;
      }

      const registryJson = buildRegistryJson();
      const failed = await submitMcpService(parsedHeaders.value, registryJson);
      if (failed) return;

      message.success(t("mcpTools.add.success"));
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.services,
      });
      queryClient.invalidateQueries({ queryKey: MCP_SERVERS_QUERY_KEY });
      await refreshToolListWithToast({
        message,
        t,
        toastKey: "mcp-tools-refresh-tools-add-community",
      });

      if (source.marketId) {
        incrementCommunityMcpDownloadCount(source.marketId).catch((err) =>
          log.warn(
            "[useMcpCommunityQuickAdd] Failed to increment download count",
            err
          )
        );
      }

      onSuccess();
      close();
    } catch (error) {
      log.error("[useMcpCommunityQuickAdd] Failed to add community service", {
        error,
      });
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
    deploymentStarted,
    containerId,
  };
}
