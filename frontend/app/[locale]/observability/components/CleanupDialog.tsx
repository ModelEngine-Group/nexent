// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Alert, InputNumber } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { StandardModal } from "@/components/common/StandardModal";
import { StandardButton } from "@/components/common/StandardButton";
import { useTrajectoryCleanup } from "@/hooks/trajectory/useTrajectoryCleanup";
import { formatMetric, formatTraceTime } from "@/lib/trajectory";
import { TrajectoryError } from "./TrajectoryFeedback";

export function CleanupDialog({
  onClose,
  onComplete,
}: {
  onClose: () => void;
  onComplete: () => void;
}) {
  const { t } = useTranslation();
  const [days, setDays] = useState<number | null>(30);
  const cleanup = useTrajectoryCleanup(onComplete);
  const close = () => {
    cleanup.cancel();
    onClose();
  };
  const result = cleanup.result;
  const valid =
    days != null && Number.isInteger(days) && days >= 1 && days <= 3650;
  const partial =
    !!result && (result.pending_runs > 0 || result.failed_runs > 0);
  return (
    <StandardModal
      open
      title={t("trajectory.cleanup")}
      closeLabel={t("trajectory.close")}
      cancelText={t("trajectory.close")}
      confirmText={t("trajectory.confirmCleanup")}
      onOpenChange={(open) => {
        if (!open) close();
      }}
      footer={
        <div className="flex justify-end gap-4">
          <StandardButton onClick={close}>
            {cleanup.running
              ? t("trajectory.stopCleanup")
              : t("trajectory.close")}
          </StandardButton>
          <StandardButton
            variant="primary"
            disabled={!valid || cleanup.running}
            onClick={() => void cleanup.start(days!, !!cleanup.error)}
          >
            {cleanup.error
              ? t("trajectory.retry")
              : t("trajectory.confirmCleanup")}
          </StandardButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <Alert
          type="warning"
          showIcon
          title={t("trajectory.cleanupScope")}
          description={t("trajectory.cleanupWarning")}
        />
        <label>
          {t("trajectory.beforeDays")}{" "}
          <InputNumber
            aria-label={t("trajectory.beforeDays")}
            min={1}
            max={3650}
            precision={0}
            value={days}
            disabled={cleanup.running || !!cleanup.error}
            onChange={setDays}
          />
        </label>
        {cleanup.error != null && (
          <TrajectoryError
            error={cleanup.error}
            retry={() => void cleanup.start(days!, true)}
          />
        )}
        {result && (
          <>
            <Alert
              type={partial ? "warning" : result.done ? "success" : "info"}
              title={t(
                partial
                  ? "trajectory.cleanupPartial"
                  : result.done
                    ? "trajectory.cleanupDone"
                    : "trajectory.cleanupRunning"
              )}
            />
            <dl className="trajectory-info">
              <dt>{t("trajectory.cutoff")}</dt>
              <dd>{formatTraceTime(result.cutoff_at)}</dd>
              {(
                [
                  "scanned_runs",
                  "deleted_runs",
                  "deleted_bytes",
                  "skipped_active",
                  "pending_runs",
                  "failed_runs",
                ] as const
              ).map((key) => (
                <div className="contents" key={key}>
                  <dt>{t(`trajectory.cleanupStats.${key}`)}</dt>
                  <dd>{formatMetric(result[key], 0)}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
      </div>
    </StandardModal>
  );
}
