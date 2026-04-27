"use client";

import { useState } from "react";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  disableMcpToolService,
  enableMcpToolService,
} from "@/services/mcpToolsService";
import { updateToolList } from "@/services/mcpService";
import { McpServiceStatus } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

/**
 * Toggles the enabled/disabled flag on an MCP service and refreshes caches that
 * depend on it. Tracks per-service loading so multiple toggles can be in-flight
 * at once without interfering.
 */
export function useMcpServiceToggle() {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const [toggling, setToggling] = useState<Record<number, boolean>>({});

  const isToggling = (mcpId?: number) =>
    typeof mcpId === "number" ? Boolean(toggling[mcpId]) : false;

  const setToggle = (mcpId: number, value: boolean) =>
    setToggling((prev) => ({ ...prev, [mcpId]: value }));

  const toggle = async (service: McpServiceItem) => {
    if (typeof service.mcpId !== "number" || service.mcpId < 0) {
      message.warning(t("mcpTools.service.toggle.missingId"));
      return;
    }
    const nextEnabled = service.status !== McpServiceStatus.ENABLED;
    setToggle(service.mcpId, true);
    try {
      if (nextEnabled) {
        await enableMcpToolService({ mcp_id: service.mcpId, enabled: true });
      } else {
        await disableMcpToolService({ mcp_id: service.mcpId, enabled: false });
      }
      message.success(
        nextEnabled
          ? t("mcpTools.service.enabled")
          : t("mcpTools.service.disabled")
      );
      try {
        await updateToolList();
      } catch (error) {
        log.error("[useMcpServiceToggle] Failed to refresh tool list", {
          error,
        });
      }
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.services,
      });
      queryClient.invalidateQueries({ queryKey: ["tools"] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    } catch (error) {
      log.error("[useMcpServiceToggle] Failed to toggle service", {
        error,
        serviceName: service.name,
        serverUrl: service.serverUrl,
      });
      message.error(t("mcpTools.service.toggle.failed"));
      throw error;
    } finally {
      setToggle(service.mcpId, false);
    }
  };

  return { toggle, isToggling };
}
