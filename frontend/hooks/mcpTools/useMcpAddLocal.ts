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
import { McpDeploymentType, McpSource, MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";
import type { LocalAddMcpDraft } from "@/types/mcpTools";
import { refreshToolListWithToast } from "./useRefreshToolListWithToast";
import { uploadMcpImage } from "@/services/mcpService";

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

    const isContainer = draft.deploymentType === McpDeploymentType.CONTAINER;
    const isApi = draft.deploymentType === McpDeploymentType.API;
    const isLocalImage = draft.deploymentType === McpDeploymentType.LOCAL_IMAGE;
    if (isContainer || isLocalImage) {
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

    // Parse OpenAPI JSON for API type
    let configJson: Record<string, unknown> | undefined;
    if (isApi) {
      const raw = (draft.openApiJson ?? "").trim();
      if (!raw) {
        message.error(t("mcpConfig.openApiToMcp.message.invalidJson"));
        return false;
      }
      try {
        configJson = JSON.parse(raw);
      } catch {
        message.error(t("mcpConfig.openApiToMcp.message.invalidJson"));
        return false;
      }
    }

    setSubmitting(true);
    try {
      if (isLocalImage) {
        const file = draft.uploadImageFile;
        if (!file) {
          message.error(t("mcpConfig.message.uploadImageFileRequired"));
          return false;
        }
        if (!file.name.endsWith(".tar")) {
          message.error(t("mcpConfig.message.uploadImageInvalidFileType"));
          return false;
        }
        if (!draft.containerPort || draft.containerPort < 1 || draft.containerPort > 65535) {
          message.error(t("mcpConfig.message.uploadImageValidPortRequired"));
          return false;
        }

        const envVars = draft.authorizationToken?.trim()
          ? JSON.stringify({ authorization_token: draft.authorizationToken.trim() })
          : undefined;

        await uploadMcpImage(file, draft.containerPort, trimmedName, envVars);
      } else if (isContainer) {
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
          config_json: configJson,
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
