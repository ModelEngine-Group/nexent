// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import type { AgentTokenUsage } from "@/types/agentMonitoring";
import type { MonitoringPublication } from "@/types/operations";
import { formatAgentMetric } from "./agentMonitoringValues";
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

export function TokenCoverage({ usage }: { usage: AgentTokenUsage | null }) {
  const { t, i18n } = useTranslation("common");
  if (usage === null)
    return <span>{t("ops.monitoring.agent.coverageMissing")}</span>;
  const number = new Intl.NumberFormat(i18n.language);
  return (
    <span>
      {t("ops.monitoring.agent.requestCoverage", {
        known: number.format(usage.known_count),
        eligible: number.format(usage.eligible_count),
        rate: formatAgentMetric(
          usage.coverage_rate,
          "success_rate",
          i18n.language
        ),
      })}
    </span>
  );
}
