// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { Alert, InputNumber, Spin } from "antd";
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
  const [editedMinutes, setEditedMinutes] = useState<
    number | null | undefined
  >();
  const minutes =
    editedMinutes === undefined
      ? (query.data?.interval_seconds ?? 0) / 60
      : editedMinutes;
  const valid =
    minutes != null &&
    Number.isInteger(minutes) &&
    minutes >= 1 &&
    minutes <= 525600;
  const save = () => {
    if (!valid || !query.data || query.isError || mutation.isPending) return;
    mutation.mutate(minutes! * 60, {
      onSuccess: () => setEditedMinutes(undefined),
    });
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
            <Alert
              type={query.data.enabled ? "info" : "warning"}
              showIcon
              title={t(
                query.data.enabled
                  ? "trajectory.schedulePolicy"
                  : "trajectory.scheduleDisabled",
                { days: query.data.retention_days }
              )}
              description={t("trajectory.scheduleHelp")}
            />
            <label className="flex items-center gap-3">
              <span>{t("trajectory.cleanupIntervalMinutes")}</span>
              <InputNumber
                aria-label={t("trajectory.cleanupIntervalMinutes")}
                min={1}
                max={525600}
                precision={0}
                value={minutes}
                disabled={mutation.isPending}
                onChange={(value) => {
                  setEditedMinutes(value);
                  mutation.reset();
                }}
              />
            </label>
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
