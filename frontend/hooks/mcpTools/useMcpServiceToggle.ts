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
import { refreshToolListWithToast } from "./useRefreshToolListWithToast";
import { McpServiceStatus } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";

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
  const [refreshingTools, setRefreshingTools] = useState<Record<number, boolean>>(
    {}
  );

  const isToggling = (mcpId?: number) =>
    typeof mcpId === "number" ? Boolean(toggling[mcpId]) : false;

  const setToggle = (mcpId: number, value: boolean) =>
    setToggling((prev) => ({ ...prev, [mcpId]: value }));

  const isRefreshing = (mcpId?: number) =>
    typeof mcpId === "number" ? Boolean(refreshingTools[mcpId]) : false;

  const toggle = async (service: McpServiceItem): Promise<McpServiceStatus> => {
    if (typeof service.mcpId !== "number" || service.mcpId < 0) {
      message.warning(t("mcpTools.service.toggle.missingId"));
      throw new Error("Missing MCP id");
    }
    const nextEnabled = service.enabled !== McpServiceStatus.ENABLED;
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
      const nextStatus = nextEnabled ? McpServiceStatus.ENABLED : McpServiceStatus.DISABLED;

      // Fire-and-forget tool scan / refresh. UI should update immediately after
      // enable/disable succeeds, without waiting for scan_tools.
      setRefreshingTools((prev) => ({ ...prev, [service.mcpId]: true }));
      void refreshToolListWithToast({
        message,
        t,
        toastKey: `mcp-tools-refresh-${service.mcpId}`,
      })
        .then(() => {
          queryClient.invalidateQueries({ queryKey: ["tools"] });
          queryClient.invalidateQueries({ queryKey: ["agents"] });
        })
        .finally(() => {
          setRefreshingTools((prev) => ({ ...prev, [service.mcpId]: false }));
        });

      return nextStatus;
    } catch (error) {
      log.error("[useMcpServiceToggle] Failed to toggle service", {
        error,
        serviceName: service.name,
        serverUrl: service.serverUrl,
      });
      message.error(t("mcpTools.service.toggleFailed"));
      throw error;
    } finally {
      setToggle(service.mcpId, false);
    }
  };

  return { toggle, isToggling, isRefreshing };
}
