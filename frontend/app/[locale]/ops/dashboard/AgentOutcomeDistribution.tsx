// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Alert, Empty, Spin } from "antd";
import { useId, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { PublicationStatus } from "./AgentMonitoringStatus";
import {
  formatAgentMetric,
  getAgentOutcomeDistribution,
} from "./agentMonitoringValues";
import type { useAgentMonitoring } from "./useAgentMonitoring";
import styles from "./agentMonitoring.module.css";

export function AgentOutcomeDistribution({
  summary,
  loading,
  hasRange,
}: {
  summary: ReturnType<typeof useAgentMonitoring>["summary"];
  loading: boolean;
  hasRange: boolean;
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const response = summary.data;
  const metrics = response?.data;
  const distribution = metrics && getAgentOutcomeDistribution(metrics);
  const number = (value: number | null) =>
    formatAgentMetric(value, "execution_count", i18n.language);
  const rate = (value: number) =>
    formatAgentMetric(value, "success_rate", i18n.language);

  return (
    <section
      aria-labelledby={titleId}
      aria-busy={loading || summary.isFetching}
      className={styles.trend}
      data-chart-palette="default"
    >
      <header className={styles.trendHeader}>
        <h3 id={titleId}>{t("ops.monitoring.agent.outcomes.title")}</h3>
      </header>
      {summary.isError && (
        <Alert
          type="error"
          showIcon
          title={t("ops.monitoring.agent.outcomes.failed")}
        />
      )}
      {loading && !response ? (
        <div className={styles.chartState}>
          <Spin aria-label={t("common.loading")} />
        </div>
      ) : (
        <>
          {!distribution && !summary.isError && (
            <Empty
              className={styles.chartState}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t(
                hasRange
                  ? "ops.monitoring.agent.outcomes.empty"
                  : "ops.monitoring.chooseRange"
              )}
            />
          )}
          {metrics && (
            <div className={distribution ? styles.outcomes : undefined}>
              {distribution && (
                <div
                  className={styles.outcomeRing}
                  style={
                    {
                      "--success-share": `${distribution.succeededShare * 100}%`,
                    } as CSSProperties
                  }
                >
                  <div>
                    <strong>{number(distribution.samples)}</strong>
                    <span>{t("ops.monitoring.agent.outcomes.included")}</span>
                  </div>
                </div>
              )}
              <dl className={styles.outcomeLegend}>
                <div>
                  <dt>{t("ops.monitoring.agent.execution")}</dt>
                  <dd>{number(metrics.execution_count)}</dd>
                </div>
                {distribution && (
                  <>
                    <div className={styles.outcomeSuccess}>
                      <dt>
                        {t("ops.monitoring.agent.outcomes.succeeded")} ·{" "}
                        {rate(distribution.succeededShare)}
                      </dt>
                      <dd>{number(distribution.succeeded)}</dd>
                    </div>
                    <div className={styles.outcomeFailure}>
                      <dt>
                        {t("ops.monitoring.agent.outcomes.failedLabel")} ·{" "}
                        {rate(distribution.failedShare)}
                      </dt>
                      <dd>{number(distribution.failed)}</dd>
                    </div>
                  </>
                )}
              </dl>
            </div>
          )}
        </>
      )}
      {response && (
        <PublicationStatus
          label={t("ops.monitoring.agent.executionStatus")}
          publication={response}
        />
      )}
    </section>
  );
}
