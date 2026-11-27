// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Tooltip } from "antd";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import type { AgentTokenUsage } from "@/types/agentMonitoring";
import type { MonitoringPublication } from "@/types/operations";
import { formatAgentMetric } from "./agentMonitoringValues";
import { formatCompactMonitoringTokens } from "./components/shared/formatMonitoringTokens";
import styles from "./agentMonitoring.module.css";

export function PublicationStatus({
  label,
  publication,
}: {
  label: string;
  publication: MonitoringPublication;
}) {
  const { t } = useTranslation("common");
  return (
    <p className={styles.publication}>
      <strong>{label}</strong>
      <span>
        {t(`ops.monitoring.agent.coverage.${publication.coverage_state}`)}
      </span>
      {publication.is_stale && (
        <span className={styles.stale}>{t("ops.monitoring.agent.stale")}</span>
      )}
      <span>
        {t("ops.monitoring.agent.publishedAt", {
          date: publication.data_as_of
            ? dayjs
                .utc(publication.data_as_of)
                .format("YYYY-MM-DD HH:mm:ss [UTC]")
            : "—",
        })}
      </span>
    </p>
  );
}

export function MonitoringTokenCardValue({
  usage,
  loading,
}: {
  usage: AgentTokenUsage | null;
  loading: boolean;
}) {
  const { t, i18n } = useTranslation("common");
  if (loading) return <strong>{t("common.loading")}</strong>;
  const value = usage?.value ?? null;
  const display = formatCompactMonitoringTokens(value, i18n.language);
  if (value === null) return <strong>{display}</strong>;
  return (
    <Tooltip title={formatAgentMetric(value, "total_tokens", i18n.language)}>
      <strong tabIndex={0} className={styles.tokenCardValue}>
        {display}
      </strong>
    </Tooltip>
  );
}
