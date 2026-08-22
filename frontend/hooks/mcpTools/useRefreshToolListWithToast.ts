import type { MessageInstance } from "antd/es/message/interface";
import type { TFunction } from "i18next";
import log from "@/lib/logger";
import { updateToolList } from "@/services/mcpService";
import { refreshMcpToolCount } from "@/services/mcpToolsService";

type RefreshToolListWithToastParams = {
  message: MessageInstance;
  t: TFunction;
  toastKey: string;
  mcpId?: number;
};

export async function refreshToolListWithToast({
  message,
  t,
  toastKey,
  mcpId,
}: RefreshToolListWithToastParams) {
  message.open({
    key: toastKey,
    type: "loading",
    content: t("mcpTools.tools.refreshing"),
    duration: 0,
  });
  try {
    // Refresh the MCP-specific snapshot first. The generic tool scan only
    // updates the agent tool registry and cannot discover changed MCP tools.
    if (mcpId !== undefined) {
      await refreshMcpToolCount(mcpId);
    }
    await updateToolList();
  } catch (error) {
    log.error("[refreshToolListWithToast] Failed to refresh tool list", {
      error,
    });
  } finally {
    message.destroy(toastKey);
  }
}
