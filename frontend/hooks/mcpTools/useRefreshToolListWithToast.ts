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
    if (typeof mcpId === "number") {
      await refreshMcpToolCount(mcpId);
    }
    const result = await updateToolList();
    if (!result.success) {
      throw new Error(result.message);
    }
  } catch (error) {
    log.error("[refreshToolListWithToast] Failed to refresh tool list", {
      error,
    });
    message.error(t("mcpTools.tools.loadFailed"));
  } finally {
    message.destroy(toastKey);
  }
}
