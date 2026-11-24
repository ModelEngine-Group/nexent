// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Empty, Table } from "antd";
import type { LucideIcon } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import styles from "../../agentMonitoring.module.css";
import { MonitoringColumnSearch } from "./MonitoringColumnSearch";
import layoutStyles from "./unavailableMonitoring.module.css";

export function UnavailableMonitoring({
  summaryLabel,
  cards,
  trendTitle,
  rankingTitle,
  details,
}: {
  summaryLabel: string;
  cards: { title: string; Icon: LucideIcon }[];
  trendTitle: string;
  rankingTitle?: string;
  details: {
    title: string;
    nameLabel: string;
    searchLabel: string;
    columns: { key: string; title: string }[];
  };
}) {
  const { t } = useTranslation("common");
  const metricsId = useId();
  const detailsId = useId();
  const unavailable = t("ops.monitoring.notConnected");
  const columns = [
    {
      title: (
        <span className={styles.displayNameHeader}>
          {details.nameLabel}
          <MonitoringColumnSearch
            search=""
            placeholder={details.searchLabel}
            disabled
            onSubmit={() => undefined}
          />
        </span>
      ),
      key: "name",
    },
    ...details.columns,
  ];
  const chartState = (
    <div className={styles.chartState}>
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={unavailable} />
    </div>
  );

  return (
    <>
      <section className={styles.panels} aria-labelledby={metricsId}>
        <dl className={styles.cards} aria-label={summaryLabel}>
          {cards.map(({ title, Icon }) => (
            <div
              key={title}
              className={
                cards.length > 1
                  ? `${styles.card} ${layoutStyles.centeredCard}`
                  : styles.card
              }
            >
              <Icon className={styles.icon} size={26} aria-hidden />
              <div>
                <dt>{title}</dt>
                <dd>
                  <strong>—</strong>
                  <small>{unavailable}</small>
                </dd>
              </div>
            </div>
          ))}
        </dl>
        <h2 id={metricsId} className={styles.metricsTitle}>
          {t("ops.monitoring.agent.metrics")}
        </h2>
        <div className={rankingTitle ? styles.charts : undefined}>
          <section className={styles.trend} aria-label={trendTitle}>
            <div className={styles.trendHeader}>
              <div>
                <h3>{trendTitle}</h3>
                <span>{t("ops.monitoring.agent.daily")}</span>
              </div>
            </div>
            {chartState}
          </section>
          {rankingTitle && (
            <section className={styles.trend} aria-label={rankingTitle}>
              <div className={styles.trendHeader}>
                <h3>{rankingTitle}</h3>
              </div>
              {chartState}
            </section>
          )}
        </div>
      </section>
      <section className={styles.details} aria-labelledby={detailsId}>
        <h2 id={detailsId} className={styles.detailsHeading}>
          {details.title}
        </h2>
        <Table
          columns={columns}
          dataSource={[]}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={unavailable}
              />
            ),
          }}
          pagination={false}
          size="small"
        />
      </section>
    </>
  );
}
