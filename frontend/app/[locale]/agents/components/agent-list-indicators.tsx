// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { getMineCardRepositoryStatusBadge } from "@/lib/agentRepositoryMine";
import { getUnavailableReasonLabels } from "@/lib/agentLabelMapper";
import type { Agent } from "@/types/agentConfig";

export default function AgentListIndicators({ agent }: { agent: Agent }) {
  const { t } = useTranslation("common");
  const badge = getMineCardRepositoryStatusBadge(agent.repository_info ?? []);
  const repositoryLabel = badge
    ? `${t(badge.labelKey)}${badge.versionLabel ? ` · ${badge.versionLabel}` : ""}`
    : "";
  const unavailableLabel =
    getUnavailableReasonLabels(agent.unavailable_reasons ?? [], t).join(", ") ||
    t("agentSelector.agentUnavailable");
  if (!badge && agent.is_available !== false) return null;

  return (
    <span className="inline-flex min-w-0 max-w-[60%] shrink-0 items-center gap-1 text-[11px] leading-4">
      {badge ? (
        <Tooltip title={repositoryLabel}>
          <span
            aria-label={repositoryLabel}
            className={`max-w-24 truncate rounded px-1 py-0.5 ${
              badge.variant === "pending"
                ? "bg-amber-50 text-amber-700"
                : badge.variant === "rejected"
                  ? "bg-rose-50 text-rose-700"
                  : "bg-blue-50 text-blue-700"
            }`}
          >
            {repositoryLabel}
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
