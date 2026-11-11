// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { getUnavailableReasonLabels } from "@/lib/agentLabelMapper";
import type { Agent } from "@/types/agentConfig";

export default function AgentListIndicators({ agent }: { agent: Agent }) {
  const { t } = useTranslation("common");
  const currentVersionNo = agent.current_version_no ?? 0;
  const publishedVersionLabel =
    currentVersionNo > 0
      ? agent.version_label?.trim() || `V${currentVersionNo}`
      : "";
  const unavailableLabel =
    getUnavailableReasonLabels(agent.unavailable_reasons ?? [], t).join(", ") ||
    t("agentSelector.agentUnavailable");
  if (!publishedVersionLabel && agent.is_available !== false) return null;

  return (
    <span className="inline-flex min-w-0 max-w-[60%] shrink-0 items-center gap-1 text-[11px] leading-4">
      {publishedVersionLabel ? (
        <Tooltip title={publishedVersionLabel}>
          <span className="max-w-24 truncate rounded bg-blue-50 px-1 py-0.5 text-blue-700">
            {publishedVersionLabel}
          </span>
        </Tooltip>
      ) : null}

      {agent.is_available === false ? (
        <Tooltip title={unavailableLabel}>
          <span
            aria-label={unavailableLabel}
            className="shrink-0 rounded bg-red-50 px-1 py-0.5 text-red-700"
          >
            {t("mcpConfig.status.unavailable")}
          </span>
        </Tooltip>
      ) : null}
    </span>
  );
}
