// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Alert, InputNumber, Button, Modal } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useTrajectoryCleanup } from "@/hooks/trajectory/useTrajectoryCleanup";
import { formatMetric, formatTraceTime } from "@/lib/trajectory";
import { TrajectoryError } from "./TrajectoryFeedback";
import { DirectoryFilter } from "./DirectoryFilter";
import type { DirectoryOption } from "@/types/trajectory";

export function CleanupDialog({
  onClose,
  onComplete,
  tenantId,
  selectTenant = false,
}: {
  onClose: () => void;
  onComplete: () => void;
  tenantId?: string;
  selectTenant?: boolean;
}) {
  const { t } = useTranslation();
  const [days, setDays] = useState<number | null>(30);
  const [tenant, setTenant] = useState<DirectoryOption>();
  const target = selectTenant ? tenant?.id : tenantId;
  const cleanup = useTrajectoryCleanup(onComplete, target);
  const close = () => {
    if (!cleanup.running) onClose();
  };
  const result = cleanup.result;
  const valid =
    days != null &&
    Number.isInteger(days) &&
    days >= 1 &&
    days <= 30 &&
    (!selectTenant || !!target);
  const tenantLocked = cleanup.running || !!cleanup.result || !!cleanup.error;
  const partial =
    !!result && (result.pending_runs > 0 || result.failed_runs > 0);
  const completed = !!result?.done && !partial;
  useEffect(() => {
    if (completed && !cleanup.running && !cleanup.error) onClose();
  }, [completed, cleanup.running, cleanup.error, onClose]);
  return (
    <Modal
      open
      title={t("trajectory.cleanup")}
      centered
      closable={
        cleanup.running ? false : { "aria-label": t("trajectory.close") }
      }
      keyboard={!cleanup.running}
      mask={{ closable: false }}
      cancelText={t("trajectory.close")}
      onCancel={close}
      footer={
        <div className="flex justify-end gap-4">
          {!cleanup.running && (
            <Button onClick={close}>{t("trajectory.close")}</Button>
          )}
          <Button
            type="primary"
            disabled={!valid || cleanup.running}
            onClick={() => void cleanup.start(days!, !!cleanup.error)}
          >
            {cleanup.error
              ? t("trajectory.retry")
              : t("trajectory.confirmCleanup")}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <Alert
          type="warning"
          showIcon
          title={t(
            selectTenant
              ? tenant
                ? "trajectory.cleanupSelectedScope"
                : "trajectory.selectCleanupTenant"
              : "trajectory.cleanupScope",
            { tenant: tenant?.name }
          )}
          description={t("trajectory.cleanupWarning")}
        />
        {selectTenant && (
          <div className="flex items-center gap-3">
            <span>{t("trajectory.tenants")}</span>
            {tenantLocked ? (
              <span>{tenant?.name || t("trajectory.unnamedOption")}</span>
            ) : (
              <DirectoryFilter
                facet="tenants"
                filters={{}}
                value={tenant?.id}
                onChange={setTenant}
              />
            )}
          </div>
        )}
        <label>
          {t("trajectory.beforeDays")}{" "}
          <InputNumber
            aria-label={t("trajectory.beforeDays")}
            min={1}
            max={30}
            precision={0}
            value={days}
            disabled={cleanup.running || !!cleanup.error}
            onInput={(value) =>
              setDays(value.trim() === "" ? null : Number(value))
            }
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
    </Modal>
  );
}
