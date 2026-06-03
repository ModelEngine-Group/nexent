"use client";

import { useState } from "react";
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
import type { LocalAddMcpDraft } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";
import { refreshToolListWithToast } from "./useRefreshToolListWithToast";

interface UseMcpAddLocalParams {
  onSuccess: () => void;
}

/**
 * Submission mutation for the "Add local MCP" form. The component owns the
 * draft; this hook only cares about the network call + cache invalidation.
 */
export function useMcpAddLocal({ onSuccess }: UseMcpAddLocalParams) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const [submitting, setSubmitting] = useState(false);

  const submit = async (draft: LocalAddMcpDraft): Promise<boolean> => {
    const trimmedName = draft.name.trim();
    if (!trimmedName) {
      message.warning(t("mcpTools.add.validate.nameRequired"));
      return false;
    }

    const isContainer = draft.transportType === McpTransportType.CONTAINER;
    if (isContainer) {
      const available = await checkContainerPortAvailable(draft.containerPort);
      if (!available) {
        message.error(
          t("mcpTools.addModal.portOccupied", { port: draft.containerPort })
        );
        return false;
      }
    }

    // Parse custom headers JSON if provided
    let customHeaders: Record<string, string> | undefined;
    if (draft.customHeaders?.trim()) {
      try {
        customHeaders = JSON.parse(draft.customHeaders.trim());
      } catch {
        message.error(t("mcpConfig.message.invalidCustomHeadersJson"));
        return false;
      }
    }

    setSubmitting(true);
    try {
      if (isContainer) {
        const mcpConfig = parseContainerMcpConfigJson(draft.containerConfigJson);
        if (!mcpConfig) {
          message.error(t("mcpTools.add.error.containerJsonInvalid"));
          return false;
        }

        await addContainerMcpToolService({
          name: trimmedName,
          description: draft.description ?? "",
          tags: draft.tags,
          source: McpSource.LOCAL,
          authorization_token: draft.authorizationToken?.trim() || undefined,
          port: draft.containerPort as number,
          mcp_config: mcpConfig,
        });
      } else {
        await addMcpToolService({
          name: trimmedName,
          description: draft.description ?? "",
          source: McpSource.LOCAL,
          server_url: draft.serverUrl.trim(),
          authorization_token: draft.authorizationToken?.trim() || undefined,
          custom_headers: customHeaders,
          tags: draft.tags,
        });
      }

      message.success(t("mcpTools.add.success"));
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.services,
      });
      await refreshToolListWithToast({
        message,
        t,
        toastKey: "mcp-tools-refresh-tools-add-local",
      });
      onSuccess();
      return true;
    } catch (error) {
      log.error("[useMcpAddLocal] Failed to add service", { error });
      message.error(t("mcpTools.add.failed"));
      return false;
    } finally {
      setSubmitting(false);
    }
  };

  return { submit, submitting };
}
