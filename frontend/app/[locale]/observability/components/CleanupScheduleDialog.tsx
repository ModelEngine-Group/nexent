// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { Alert, InputNumber, Spin, Switch } from "antd";
import { useTranslation } from "react-i18next";
import { StandardModal } from "@/components/common/StandardModal";
import { StandardButton } from "@/components/common/StandardButton";
import { useCleanupSchedule } from "@/hooks/trajectory/useCleanupSchedule";
import { TrajectoryError } from "./TrajectoryFeedback";

interface CleanupScheduleDialogProps {
  scope: string;
  tenantId: string;
  onClose: () => void;
}

export function CleanupScheduleDialog({
  scope,
  tenantId,
  onClose,
}: CleanupScheduleDialogProps) {
  const { t } = useTranslation();
  const { query, mutation } = useCleanupSchedule(scope, tenantId);
  const [editedDays, setEditedDays] = useState<number | null | undefined>();
  const [editedEnabled, setEditedEnabled] = useState<boolean | undefined>();
  const days =
    editedDays === undefined ? query.data?.retention_days : editedDays;
  const enabled = editedEnabled ?? query.data?.enabled ?? false;
  const valid =
    days != null && Number.isInteger(days) && days >= 1 && days <= 30;
  const save = () => {
    if (!valid || !query.data || query.isError || mutation.isPending) return;
    mutation.mutate(
      { enabled, retention_days: days! },
      {
        onSuccess: () => {
          setEditedDays(undefined);
          setEditedEnabled(undefined);
        },
      }
    );
  };
  return (
    <StandardModal
      open
      title={t("trajectory.scheduledCleanup")}
      closeLabel={t("trajectory.close")}
      cancelText={t("trajectory.close")}
      confirmText={t("trajectory.saveSchedule")}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      footer={
        <div className="flex justify-end gap-4">
          <StandardButton onClick={onClose}>
            {t("trajectory.close")}
          </StandardButton>
          <StandardButton
            variant="primary"
            disabled={
              !valid || !query.data || query.isError || mutation.isPending
            }
            onClick={save}
          >
            {t(
              mutation.isPending
                ? "trajectory.savingSchedule"
                : "trajectory.saveSchedule"
            )}
          </StandardButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {query.isPending && <Spin />}
        {query.isError && (
          <TrajectoryError
            error={query.error}
            retry={() => void query.refetch()}
          />
        )}
        {query.data && !query.isError && (
          <>
            <label className="flex items-center justify-between gap-3">
              <span>{t("trajectory.scheduleEnabled")}</span>
              <Switch
                aria-label={t("trajectory.scheduleEnabled")}
                checked={enabled}
                disabled={mutation.isPending}
                onChange={(value) => {
                  setEditedEnabled(value);
                  mutation.reset();
                }}
              />
            </label>
            <label className="flex items-center gap-3">
              <span>{t("trajectory.beforeDays")}</span>
              <InputNumber
                aria-label={t("trajectory.beforeDays")}
                min={1}
                max={30}
                precision={0}
                value={days}
                disabled={!enabled || mutation.isPending}
                onInput={(value) => {
                  setEditedDays(value.trim() === "" ? null : Number(value));
                  mutation.reset();
                }}
                onChange={(value) => {
                  setEditedDays(value);
                  mutation.reset();
                }}
              />
            </label>
            <Alert
              type="info"
              showIcon
              title={t("trajectory.scheduleTime")}
              description={t("trajectory.scheduleHelp")}
            />
          </>
        )}
        {mutation.isError && (
          <TrajectoryError error={mutation.error} retry={save} />
        )}
        {mutation.isSuccess && (
          <Alert
            type="success"
            showIcon
            title={t("trajectory.scheduleSaved")}
          />
        )}
      </div>
    </StandardModal>
  );
}
