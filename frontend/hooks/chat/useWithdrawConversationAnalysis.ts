// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useContext } from "react";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { conversationService } from "@/services/conversationService";

export function conversationAnalysisKey(id: number, tenant?: string, user?: string) {
  return ["conversation-evolution", tenant, user, id] as const;
}

export function useWithdrawConversationAnalysis() {
  const { t } = useTranslation();
  const user = useContext(AuthorizationContext)?.user;
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();
  const client = useQueryClient();

  if (!user) return undefined;

  return (id: number) => {
    if (!Number.isSafeInteger(id) || id <= 0) return;
    confirm({
      title: t("chat.evolution.withdraw"),
      content: t("chat.evolution.withdrawConfirm"),
      onOk: async () => {
        try {
          await conversationService.evolutionSetting(id, "revoke");
          await client.invalidateQueries({
            queryKey: conversationAnalysisKey(id, user.tenantId, user.id),
            exact: true,
          });
          message.success(t("chat.evolution.withdrawSuccess"));
        } catch (error) {
          message.error(t("chat.evolution.withdrawError"));
          throw error;
        }
      },
    });
  };
}
