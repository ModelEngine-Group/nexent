// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Empty, Table } from "antd";
import { Activity, Puzzle } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import styles from "../../agentMonitoring.module.css";
import { MonitoringColumnSearch } from "../shared/MonitoringColumnSearch";
import skillStyles from "./skillMonitoring.module.css";

export function SkillMonitoring({ singleSkill }: { singleSkill: boolean }) {
  const { t } = useTranslation("common");
  const metricsId = useId();
  const detailsId = useId();
  const unavailable = t("ops.monitoring.notConnected");
  const cards = [
    ...(!singleSkill ? [{ metric: "current", Icon: Puzzle }] : []),
    { metric: "usage", Icon: Activity },
  ];
  const columns = [
    {
      title: (
        <span className={styles.displayNameHeader}>
          {t("common.name")}
          <MonitoringColumnSearch
            search=""
            placeholder={t("ops.monitoring.skill.search")}
            disabled
            onSubmit={() => undefined}
          />
        </span>
      ),
      key: "name",
    },
    { title: t("common.source"), key: "source" },
    { title: t("ops.monitoring.skill.usageColumn"), key: "usage" },
    ...(!singleSkill ? [{ title: t("common.actions"), key: "actions" }] : []),
  ];
  const chartState = (
    <div className={styles.chartState}>
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={unavailable} />
    </div>
  );
  const trendTitle = t("ops.monitoring.skill.trend");
  const rankingTitle = t("ops.monitoring.skill.top");

  return (
    <>
      <section className={styles.panels} aria-labelledby={metricsId}>
        <dl
          className={styles.cards}
          aria-label={t("ops.monitoring.skill.summary")}
        >
          {cards.map(({ metric, Icon }) => (
            <div
              key={metric}
              className={
                singleSkill
                  ? styles.card
                  : `${styles.card} ${skillStyles.centeredCard}`
              }
            >
              <Icon className={styles.icon} size={26} aria-hidden />
              <div>
                <dt>{t(`ops.monitoring.skill.${metric}`)}</dt>
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
        <div className={singleSkill ? undefined : styles.charts}>
          <section className={styles.trend} aria-label={trendTitle}>
            <div className={styles.trendHeader}>
              <div>
                <h3>{trendTitle}</h3>
                <span>{t("ops.monitoring.agent.daily")}</span>
              </div>
            </div>
            {chartState}
          </section>
          {!singleSkill && (
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
          {t("ops.monitoring.skill.details")}
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
