"use client";

import { useState } from "react";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  addContainerMcpToolServiceStream,
  addMcpToolService,
  parseContainerMcpConfigJson,
} from "@/services/mcpToolsService";
import { getMcpAddErrorMessage } from "@/lib/mcpTools";
import { checkContainerPortAvailable } from "./useContainerPortAvailability";
import { McpDeploymentType, McpSource, MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";
import { MCP_SERVERS_QUERY_KEY } from "@/hooks/mcp/useMcpServerList";
import type { LocalAddMcpDraft } from "@/types/mcpTools";
import { refreshToolListWithToast } from "./useRefreshToolListWithToast";
import { uploadMcpImageStream } from "@/services/mcpService";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

interface UseMcpAddLocalParams {
  onSuccess: () => void;
  onContainerStarted?: (containerId: string) => void;
}

/**
 * Submission mutation for the "Add local MCP" form. The component owns the
 * draft; this hook only cares about the network call + cache invalidation.
 */
export function useMcpAddLocal({ onSuccess, onContainerStarted }: UseMcpAddLocalParams) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const { user } = useAuthorizationContext();
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

    // Parse OpenAPI JSON for API type. A valid OpenAPI spec is required:
    // without it the backend cannot register any tools and the record is
    // treated as a plain remote MCP instead of an API-type service.
    let configJson: Record<string, unknown> | undefined;
    if (isApi) {
      const raw = (draft.openApiJson ?? "").trim();
      if (!raw) {
        message.error(t("mcpConfig.openApiToMcp.message.jsonRequired"));
        return false;
      }
      try {
        configJson = JSON.parse(raw);
      } catch {
        message.error(t("mcpConfig.openApiToMcp.message.invalidJsonFormat"));
        return false;
      }
      if (
        !configJson ||
        typeof configJson !== "object" ||
        Array.isArray(configJson) ||
        !("openapi" in configJson)
      ) {
        message.error(t("mcpConfig.openApiToMcp.message.invalidOpenApi"));
        return false;
      }
    }

    setSubmitting(true);
    try {
      // Embed creator identity so the "我的" card can display the developer
      const registryJson: Record<string, unknown> = {};
      if (user?.email) {
        registryJson["_authorDisplayName"] = user.email;
      }

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

        const result = await uploadMcpImageStream(
          file, draft.containerPort, trimmedName, envVars,
          undefined, draft.groupIds?.join(","), draft.ingroupPermission,
          draft.sharedFields ? JSON.stringify(draft.sharedFields) : undefined,
          (containerId) => onContainerStarted?.(containerId),
        );
        if (!result.success) {
          throw new Error(result.message || t("mcpTools.add.error.imageUploadFailed"));
        }
      } else if (isContainer) {
        const mcpConfig = parseContainerMcpConfigJson(draft.containerConfigJson);
        if (!mcpConfig) {
          message.error(t("mcpTools.add.error.containerJsonInvalid"));
          return false;
        }

        await addContainerMcpToolServiceStream({
          name: trimmedName,
          description: draft.description ?? "",
          source: McpSource.LOCAL,
          authorization_token: draft.authorizationToken?.trim() || undefined,
          registry_json: registryJson,
          port: draft.containerPort as number,
          mcp_config: mcpConfig,
          group_ids: draft.groupIds?.join(",") ?? undefined,
          ingroup_permission: draft.ingroupPermission ?? undefined,
          shared_fields: draft.sharedFields ?? undefined,
        }, (result) => {
          if (result.container_id) onContainerStarted?.(result.container_id);
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
          registry_json: registryJson,
          group_ids: draft.groupIds?.join(",") ?? undefined,
          ingroup_permission: draft.ingroupPermission ?? undefined,
          shared_fields: draft.sharedFields ?? undefined,
        });
      }

      message.success(t("mcpTools.add.success"));
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.services,
      });
      queryClient.invalidateQueries({ queryKey: MCP_SERVERS_QUERY_KEY });
      await refreshToolListWithToast({
        message,
        t,
        toastKey: "mcp-tools-refresh-tools-add-local",
      });
      onSuccess();
      return true;
    } catch (error) {
      log.error("[useMcpAddLocal] Failed to add service", { error });
      message.error(getMcpAddErrorMessage(error, t));
      return false;
    } finally {
      setSubmitting(false);
    }
  };

  return { submit, submitting };
}
