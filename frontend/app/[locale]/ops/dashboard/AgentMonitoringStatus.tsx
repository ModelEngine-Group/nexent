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

function CoverageFlags({
  publication,
  partial = false,
}: {
  publication?: MonitoringPublication;
  partial?: boolean;
}) {
  const { t } = useTranslation("common");
  return (
    <>
      {(partial || publication?.coverage_state === "partial") && (
        <span>{t("ops.monitoring.agent.coverage.partial")}</span>
      )}
      {publication?.is_stale && (
        <span className={styles.stale}>{t("ops.monitoring.agent.stale")}</span>
      )}
    </>
  );
}

const statusTooltip = {
  color: "var(--color-bg-3)",
  styles: { container: { color: "var(--color-text-primary)" } },
};

export function MonitoringTokenCardValue({
  usage,
  publication,
  loading,
}: {
  usage: AgentTokenUsage | null;
  publication?: MonitoringPublication;
  loading: boolean;
}) {
  const { t, i18n } = useTranslation("common");
  if (loading) return <strong>{t("common.loading")}</strong>;
  const value = usage?.value ?? null;
  const display = formatCompactMonitoringTokens(value, i18n.language);
  if (!publication) return <strong>{display}</strong>;
  const partial =
    usage !== null &&
    usage.known_count > 0 &&
    usage.known_count < usage.eligible_count;
  return (
    <>
      <Tooltip
        {...statusTooltip}
        title={
          <div className={styles.tokenStatusTooltip}>
            <strong>
              {formatAgentMetric(value, "total_tokens", i18n.language)}
              {value !== null && " tokens"}
            </strong>
            <TokenCoverage usage={usage} />
            <PublicationStatus
              label={t("ops.monitoring.agent.tokens")}
              publication={publication}
            />
          </div>
        }
      >
        <strong tabIndex={0} className={styles.tokenCardValue}>
          {display}
        </strong>
      </Tooltip>
      {(partial ||
        publication.coverage_state === "partial" ||
        publication.is_stale) && (
        <small className={styles.dataHint}>
          <CoverageFlags publication={publication} partial={partial} />
        </small>
      )}
    </>
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
