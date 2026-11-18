// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Alert, App, Card, Flex, Switch, Typography } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { tenantMemorySettingsKey } from "@/hooks/memory/useTenantMemorySettings";
import {
  loadTenantMemorySettings,
  setTenantMemoryEnabled,
} from "@/services/memoryService";

export default function TenantMemorySettingsTab({
  userId,
  tenantId,
}: {
  userId: string;
  tenantId: string;
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const queryKey = tenantMemorySettingsKey(tenantId, userId);
  const { data, isPending, isError } = useQuery({
    queryKey,
    queryFn: loadTenantMemorySettings,
  });
  const save = useMutation({
    mutationFn: setTenantMemoryEnabled,
    onSuccess: (settings) => queryClient.setQueryData(queryKey, settings),
    onError: () => message.error(t("useMemory.setMemorySwitchError")),
  });

  const label = t("memory.manager.tenantAutomaticMemory");
  return (
    <Card loading={isPending}>
      {isError ? (
        <Alert
          type="error"
          showIcon
          title={t("memory.manager.tenantMemoryLoadError")}
        />
      ) : (
        data && (
          <Flex align="center" justify="space-between" gap={24}>
            <div>
              <Typography.Text strong>{label}</Typography.Text>
              <div>
                <Typography.Text type="secondary">
                  {t("memory.manager.tenantAutomaticMemoryHint")}
                </Typography.Text>
              </div>
            </div>
            <Switch
              aria-label={label}
              checked={data.enabled}
              disabled={!data.can_edit}
              loading={save.isPending}
              onChange={(enabled) => save.mutate(enabled)}
            />
          </Flex>
        )
      )}
    </Card>
  );
}
