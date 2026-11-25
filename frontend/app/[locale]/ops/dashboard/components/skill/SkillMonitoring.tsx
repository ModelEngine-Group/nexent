// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery } from "@tanstack/react-query";
import { Alert } from "antd";
import { Activity, Puzzle } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  getSkillMonitoringSummary,
  getSkillMonitoringTrends,
} from "@/services/skillMonitoringService";
import type { SkillMonitoringQueryKey } from "@/types/skillMonitoring";
import { formatAgentMetric } from "../../agentMonitoringValues";
import { OverviewTrend } from "../overview/OverviewTrend";
import { UnavailableMonitoring } from "../shared/UnavailableMonitoring";
import { getSkillUsageCount } from "./skillMonitoringValues";

export function SkillMonitoring({
  queryKey,
  singleSkill,
  scopeLoading,
  hasRange,
}: {
  queryKey: SkillMonitoringQueryKey;
  singleSkill: boolean;
  scopeLoading: boolean;
  hasRange: boolean;
}) {
  const { t, i18n } = useTranslation("common");
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
                Icon: Puzzle,
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
      rankingTitle={singleSkill ? undefined : t("ops.monitoring.skill.top")}
      details={{
        title: t("ops.monitoring.skill.details"),
        nameLabel: t("common.name"),
        searchLabel: t("ops.monitoring.skill.search"),
        columns: [
          { title: t("common.source"), key: "source" },
          { title: t("ops.monitoring.skill.usageColumn"), key: "usage" },
          ...(!singleSkill
            ? [{ title: t("common.actions"), key: "actions" }]
            : []),
        ],
      }}
    />
  );
}
