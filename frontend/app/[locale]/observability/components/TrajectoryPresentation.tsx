// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App, Tag } from "antd";
import { Bot, BrainCircuit, Check, Copy, Wrench, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { formatMetric, formatTraceTime } from "@/lib/trajectory";

export function NodeIcon({
  kind,
  large = false,
}: {
  kind: string;
  large?: boolean;
}) {
  const Icon =
    kind === "agent" ? Bot : kind === "model" ? BrainCircuit : Wrench;
  return (
    <span
      className={`trajectory-kind-icon kind-${kind}${large ? " is-large" : ""}`}
      aria-hidden
    >
      <Icon size={large ? 22 : 14} />
    </span>
  );
}

export function TrajectoryStatus({ status }: { status: string }) {
  const { t } = useTranslation();
  const success = status === "success" || status === "completed";
  const error = status === "error" || status === "failed";
  return (
    <Tag
      className={`trajectory-status${success ? " is-success" : error ? " is-error" : ""}`}
      color={success ? "success" : error ? "error" : "default"}
    >
      {success ? <Check size={12} /> : error ? <X size={12} /> : null}
      {t(
        success
          ? "trajectory.success"
          : error
            ? "trajectory.error"
            : ["cancelled", "interrupted"].includes(status)
              ? `trajectory.businessStatus.${status}`
              : `trajectory.availability.${status}`
      )}
    </Tag>
  );
}

export function CopyTraceId({ value }: { value: string }) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  return (
    <button
      className="trajectory-icon-button"
      aria-label={t("trajectory.copyTraceId")}
      onClick={() =>
        void navigator.clipboard.writeText(value).then(
          () => message.success(t("trajectory.copied")),
          () => message.error(t("trajectory.copyFailed"))
        )
      }
    >
      <Copy size={12} />
    </button>
  );
}

export function nodeDuration(value: number | null | undefined): string {
  return value != null && value < 1000
    ? `${formatMetric(value)} ms`
    : `${formatMetric(value == null ? null : value / 1000)} s`;
}

export function nodeTime(value: string | null): string {
  const text = formatTraceTime(value);
  return text === "—"
    ? text
    : `${text}.${String(new Date(value!).getUTCMilliseconds()).padStart(3, "0")}`;
}
