// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Switch } from "antd";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { conversationService } from "@/services/conversationService";

export function ConversationEvolutionSwitch({ id }: { id: number }) {
  const { t } = useTranslation();
  const { user } = useAuthorizationContext();
  const client = useQueryClient();
  const key = ["conversation-evolution", user?.tenantId, user?.id, id];
  const setting = useQuery({
    queryKey: key,
    queryFn: () => conversationService.evolutionSetting(id),
    enabled: Boolean(user),
  });
  const update = useMutation({
    mutationFn: (enabled: boolean) => conversationService.evolutionSetting(id, enabled),
    onSuccess: (enabled) => client.setQueryData(key, enabled),
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  });
  const label = t("chat.evolution.autoAnalysis");
  return (
    <div className="flex items-center justify-end gap-2 px-4 py-1 text-xs">
      {(setting.isError || update.isError) && (
        <span role="alert">{t("chat.evolution.settingError")}</span>
      )}
      <span>{label}</span>
      <Switch
        size="small"
        aria-label={label}
        checked={setting.data === true}
        disabled={!setting.isSuccess || update.isPending}
        onChange={(enabled) => update.mutate(enabled)}
      />
    </div>
  );
}
