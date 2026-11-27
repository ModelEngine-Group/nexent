// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Pagination, Spin, Table } from "antd";
import { Activity, Sparkles } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getSkillMonitoringList,
  getSkillMonitoringRankings,
  getSkillMonitoringSummary,
  getSkillMonitoringTrends,
} from "@/services/skillMonitoringService";
import type {
  SkillMonitoringQueryKey,
  SkillMonitoringRow,
} from "@/types/skillMonitoring";
import { formatAgentMetric } from "../../agentMonitoringValues";
import { resourceKey } from "../../useMonitoringDirectories";
import styles from "../../agentMonitoring.module.css";
import { OverviewTrend } from "../overview/OverviewTrend";
import { MonitoringColumnSearch } from "../shared/MonitoringColumnSearch";
import { UnavailableMonitoring } from "../shared/UnavailableMonitoring";
import { getSkillUsageCount } from "./skillMonitoringValues";

export function SkillMonitoring({
  queryKey,
  singleSkill,
  scopeLoading,
  hasRange,
  onView,
}: {
  queryKey: SkillMonitoringQueryKey;
  singleSkill: boolean;
  scopeLoading: boolean;
  hasRange: boolean;
  onView: (row: SkillMonitoringRow) => void;
}) {
  const { t, i18n } = useTranslation("common");
  const rankingId = useId();
  const detailsId = useId();
  const [list, setList] = useState({
    page: 1,
    pageSize: 10,
    search: "",
    sortBy: "name" as "name" | "usage_count",
    descending: false,
  });
  const selection = queryKey[3];
  const summary = useQuery({
    queryKey: [...queryKey, "summary"],
    queryFn: ({ signal }) => getSkillMonitoringSummary(selection!, signal),
    enabled: selection !== null,
  });
  const trends = useQuery({
    queryKey: [...queryKey, "trends"],
    queryFn: ({ signal }) => getSkillMonitoringTrends(selection!, signal),
    enabled: selection !== null,
  });
  const rankings = useQuery({
    queryKey: [...queryKey, "rankings"],
    queryFn: ({ signal }) => getSkillMonitoringRankings(selection!, signal),
    enabled: selection !== null && !singleSkill,
  });
  const details = useQuery({
    queryKey: [...queryKey, "list", list],
    queryFn: ({ signal }) => getSkillMonitoringList(selection!, list, signal),
    enabled: selection !== null,
  });
  const detailData = details.isError ? undefined : details.data?.data;
  const total = detailData?.total;
  if (total !== undefined) {
    const lastPage = Math.max(1, Math.ceil(total / list.pageSize));
    if (list.page > lastPage) setList({ ...list, page: lastPage });
  }
  const summaryData = summary.isError ? undefined : summary.data;
  const summaryLoading =
    scopeLoading || (selection !== null && summary.isPending);
  const trendLoading =
    scopeLoading ||
    (selection !== null && (trends.isPending || trends.isFetching));
  const metric = (value: number | null) =>
    summaryLoading && !summaryData
      ? t("common.loading")
      : formatAgentMetric(value, "execution_count", i18n.language);
  const trendTitle = t("ops.monitoring.skill.trend");
  const missingTrend =
    trends.data?.coverage_state === "uncovered" ||
    (trends.data?.data.length &&
      trends.data.data.every((day) => day.usage_count === null));
  const rankingTitle = t("ops.monitoring.skill.top");
  const ranked = rankings.data?.data ?? [];
  const maxUsage = Math.max(
    0,
    ...ranked.map((row) => row.metrics?.usage_count ?? 0)
  );
  const formatCount = (value: number | null) =>
    formatAgentMetric(value, "execution_count", i18n.language);
  const name = (row: SkillMonitoringRow) =>
    row.skill_name || `#${row.skill_id}`;
  const emptyText = t(hasRange ? "ops.empty" : "ops.monitoring.chooseRange");
  const readError = <Alert type="error" title={t("ops.loadError")} showIcon />;
  const rowKey = (row: SkillMonitoringRow) =>
    resourceKey(row.tenant_id ?? "", row.skill_id);
  const sourceLabel = (source: string | null | undefined) => {
    if (source === "official" || source === "官方")
      return t("skillPool.group.official");
    if (source === "custom" || source === "自定义")
      return t("skillPool.group.custom");
    if (source === "repository") return t("workbench.controls.repository");
    return source || "—";
  };
  return (
    <UnavailableMonitoring
      summaryLabel={t("ops.monitoring.skill.summary")}
      summaryBusy={summaryLoading || summary.isFetching}
      summaryNotice={
        summary.isError && (
          <Alert type="error" title={t("ops.loadError")} showIcon />
        )
      }
      cards={[
        ...(!singleSkill
          ? [
              {
                title: t("ops.monitoring.skill.current"),
                Icon: Sparkles,
                value: metric(summaryData?.data.current_skill_count ?? null),
              },
            ]
          : []),
        {
          title: t("ops.monitoring.skill.usage"),
          Icon: Activity,
          value: metric(summaryData ? getSkillUsageCount(summaryData) : null),
        },
      ]}
      trendTitle={trendTitle}
      trendPanel={
        <OverviewTrend
          title={trendTitle}
          description={t("ops.monitoring.agent.daily")}
          emptyDescription={missingTrend ? "—" : undefined}
          trend={{
            points: trends.data?.data.map((day) => ({
              date: day.statistic_date,
              value: day.usage_count,
            })),
            loading: trendLoading,
            failed: trends.isError,
            hasRange,
          }}
        />
      }
      rankingTitle={singleSkill ? undefined : rankingTitle}
      rankingPanel={
        !singleSkill && (
          <section
            className={styles.trend}
            aria-labelledby={rankingId}
            aria-busy={scopeLoading || rankings.isFetching}
          >
            <div className={styles.trendHeader}>
              <h3 id={rankingId}>{rankingTitle}</h3>
            </div>
            {rankings.isError ? (
              readError
            ) : scopeLoading || (selection !== null && rankings.isPending) ? (
              <div className={styles.chartState}>
                <Spin aria-label={t("common.loading")} />
              </div>
            ) : ranked.length ? (
              <ol className={styles.rankRows}>
                {ranked.map((row) => {
                  const usage = row.metrics?.usage_count ?? null;
                  return (
                    <li key={rowKey(row)} className={styles.rankRow}>
                      {row.tenant_id ? (
                        <Button
                          type="link"
                          className={styles.rankName}
                          onClick={() => onView(row)}
                        >
                          {name(row)}
                        </Button>
                      ) : (
                        <span className={styles.rankName}>{name(row)}</span>
                      )}
                      <span className={styles.rankBar} aria-hidden>
                        <span
                          style={{
                            width: `${maxUsage ? (100 * (usage ?? 0)) / maxUsage : 0}%`,
                          }}
                        />
                      </span>
                      <strong className={styles.rankValue}>
                        {formatCount(usage)}
                      </strong>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <Empty
                className={styles.chartState}
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={emptyText}
              />
            )}
          </section>
        )
      }
      detailsPanel={
        <section className={styles.details} aria-labelledby={detailsId}>
          <h2 id={detailsId} className={styles.detailsHeading}>
            {t("ops.monitoring.skill.details")}
          </h2>
          {details.isError && readError}
          <Table<SkillMonitoringRow>
            columns={[
              {
                title: (
                  <span className={styles.displayNameHeader}>
                    {t("common.name")}
                    <MonitoringColumnSearch
                      search={list.search}
                      placeholder={t("ops.monitoring.skill.search")}
                      disabled={!selection}
                      onSubmit={(search) =>
                        setList((current) => ({ ...current, search, page: 1 }))
                      }
                    />
                  </span>
                ),
                key: "name",
                render: (_, row) => name(row),
              },
              {
                title: t("common.source"),
                key: "source",
                render: (_, row) => sourceLabel(row.source),
              },
              {
                title: t("ops.monitoring.skill.usageColumn"),
                key: "usage",
                sorter: true,
                sortDirections: ["ascend", "descend"],
                sortOrder:
                  list.sortBy === "usage_count"
                    ? list.descending
                      ? "descend"
                      : "ascend"
                    : null,
                render: (_, row) =>
                  formatCount(row.metrics?.usage_count ?? null),
              },
              ...(!singleSkill
                ? [
                    {
                      title: t("common.actions"),
                      key: "actions",
                      render: (_: unknown, row: SkillMonitoringRow) =>
                        row.tenant_id ? (
                          <Button type="link" onClick={() => onView(row)}>
                            {t("ops.monitoring.skill.view")}
                          </Button>
                        ) : (
                          "—"
                        ),
                    },
                  ]
                : []),
            ]}
            rowKey={rowKey}
            dataSource={detailData?.items ?? []}
            loading={scopeLoading || (selection !== null && details.isFetching)}
            locale={{ emptyText }}
            pagination={false}
            onChange={(_, __, sorter, { action }) => {
              if (action !== "sort") return;
              const order = Array.isArray(sorter) ? null : sorter.order;
              setList((current) => ({
                ...current,
                page: 1,
                sortBy: order ? "usage_count" : "name",
                descending: order === "descend",
              }));
            }}
            size="small"
          />
          {total !== undefined && (
            <Pagination
              className={styles.detailsPagination}
              current={list.page}
              pageSize={list.pageSize}
              total={total}
              showSizeChanger
              pageSizeOptions={[10, 20, 50, 100]}
              showQuickJumper
              showTotal={(count) =>
                t("ops.monitoring.skill.details.total", {
                  total: formatCount(count),
                })
              }
              onChange={(page, pageSize) =>
                setList((current) => ({ ...current, page, pageSize }))
              }
            />
          )}
        </section>
      }
    />
  );
}
