import { useState } from "react";
import type { MessageInstance } from "antd/es/message/interface";
import { disableMcpToolService, enableMcpToolService } from "@/services/mcpToolsService";
import { updateToolList } from "@/services/mcpService";
import { ApiError } from "@/services/api";
import { MCP_SERVICE_STATUS } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";

type UseMcpToolsToggleParams = {
  loadServerList: () => Promise<{ success: boolean; data?: McpServiceItem[] }>;
  setSelectedService: React.Dispatch<React.SetStateAction<McpServiceItem | null>>;
  t: (key: string) => string;
  message: MessageInstance;
};

export function useMcpToolsToggle({
  loadServerList,
  setSelectedService,
  t,
  message,
}: UseMcpToolsToggleParams) {
  const [togglingServiceIds, setTogglingServiceIds] = useState<Set<number>>(new Set());

  const resolveToggleErrorMessage = (error: unknown, nextEnabled: boolean) => {
    if (!nextEnabled) {
      return t("mcpTools.service.toggleFailed");
    }

    if (error instanceof ApiError) {
      const code = String(error.code);
      const text = String(error.message || "").toLowerCase();

      if (code === "503" || text.includes("mcp connection failed")) {
        return t("mcpTools.error.connectionFailed");
      }
      if (text.includes("already uses this name") || text.includes("name already exists")) {
        return t("mcpTools.service.enableNameConflict");
      }
    }

    return t("mcpTools.service.toggleFailed");
  };

  const toggleServiceStatus = async (service: McpServiceItem) => {
    if (togglingServiceIds.has(service.mcpId)) {
      return;
    }

    const nextEnabled = service.status !== MCP_SERVICE_STATUS.ENABLED;
    const toastKey = `mcp-tools-toggle-${service.mcpId}`;

    setTogglingServiceIds((prev) => {
      const next = new Set(prev);
      next.add(service.mcpId);
      return next;
    });
    message.open({
      key: toastKey,
      type: "loading",
      content: nextEnabled ? t("mcpTools.service.enabling") : t("mcpTools.service.disabling"),
      duration: 0,
    });

    try {
      const mutationFn = nextEnabled ? enableMcpToolService : disableMcpToolService;
      await mutationFn({
        mcp_id: service.mcpId,
        enabled: nextEnabled,
      });

      const listResult = await loadServerList();
      const latestService = listResult.data?.find((item) => item.mcpId === service.mcpId);
      setSelectedService((prev) =>
        prev && prev.mcpId === service.mcpId
          ? latestService ?? {
              ...prev,
              status: nextEnabled ? MCP_SERVICE_STATUS.ENABLED : MCP_SERVICE_STATUS.DISABLED,
            }
          : prev
      );

      // Keep tool pool in sync after MCP service status changes.
      await updateToolList().catch(() => undefined);

      message.open({
        key: toastKey,
        type: "success",
        content: nextEnabled ? t("mcpTools.service.enabled") : t("mcpTools.service.disabled"),
      });
    } catch (error) {
      message.open({
        key: toastKey,
        type: "error",
        content: resolveToggleErrorMessage(error, nextEnabled),
      });
      throw error;
    } finally {
      setTogglingServiceIds((prev) => {
        const next = new Set(prev);
        next.delete(service.mcpId);
        return next;
      });
    }
  };

  return {
    toggleServiceStatus,
    isServiceToggling: (mcpId: number | null | undefined) =>
      typeof mcpId === "number" && togglingServiceIds.has(mcpId),
  };
}
