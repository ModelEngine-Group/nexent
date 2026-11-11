// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Alert } from "antd";
import { useTranslation } from "react-i18next";
import { StandardButton } from "@/components/common/StandardButton";
import type { Coverage } from "@/types/trajectory";

export function TrajectoryError({
  error,
  retry,
}: {
  error: unknown;
  retry: () => void;
}) {
  const { t } = useTranslation();
  const code =
    error && typeof error === "object" && "code" in error
      ? String(error.code)
      : "query_unavailable";
  return (
    <Alert
      type="error"
      showIcon
      title={t(`trajectory.errors.${code}`, {
        defaultValue: t("trajectory.errors.query_unavailable"),
      })}
      action={
        <StandardButton onClick={retry}>{t("trajectory.retry")}</StandardButton>
      }
    />
  );
}

export function CoverageNotice({ coverage }: { coverage?: Coverage }) {
  const { t } = useTranslation();
  if (!coverage || coverage.complete === true) return null;
  const reasons = [
    ...new Set([
      ...(coverage.reasons ?? []),
      ...(coverage.missing_parent ? ["missing_parent"] : []),
      ...(coverage.capture_gap ? ["capture_gap"] : []),
    ]),
  ];
  return (
    <Alert
      type="warning"
      showIcon
      title={t("trajectory.partial")}
      description={reasons
        ?.map((reason) =>
          t(`trajectory.reasons.${reason}`, { defaultValue: reason })
        )
        .join(" · ")}
    />
  );
}
