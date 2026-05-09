import type { MessageInstance } from "antd/es/message/interface";
import type { TFunction } from "i18next";
import log from "@/lib/logger";
import { updateToolList } from "@/services/mcpService";

type RefreshToolListWithToastParams = {
  message: MessageInstance;
  t: TFunction;
  toastKey: string;
};

export async function refreshToolListWithToast({
  message,
  t,
  toastKey,
}: RefreshToolListWithToastParams) {
  message.open({
    key: toastKey,
    type: "loading",
    content: t("mcpTools.tools.refreshing"),
    duration: 0,
  });
  try {
    await updateToolList();
  } catch (error) {
    log.error("[refreshToolListWithToast] Failed to refresh tool list", {
      error,
    });
  } finally {
    message.destroy(toastKey);
  }
}

