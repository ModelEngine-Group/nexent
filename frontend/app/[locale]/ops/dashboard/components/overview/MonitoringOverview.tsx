// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery } from "@tanstack/react-query";
import { Bot, Box, Layers3, Puzzle } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { getAgentMonitoringTrends } from "@/services/agentMonitoringService";
import { getModelMonitoringTrends } from "@/services/modelMonitoringService";
import {
  getSkillMonitoringSummary,
  getSkillMonitoringTrends,
} from "@/services/skillMonitoringService";
import { agentMonitoringSelection } from "../../agentMonitoringValues";
import {
  getMonitoringRange,
  type MonitoringRange,
} from "../../monitoringFilters";
import type { useMonitoringDirectories } from "../../useMonitoringDirectories";
import { OverviewTrend } from "./OverviewTrend";
import { countOverviewResources } from "./overviewCounts";
import styles from "./overview.module.css";

const resources = [
  { kind: "agent", Icon: Bot },
  { kind: "model", Icon: Box },
  { kind: "mcp", Icon: Layers3 },
  { kind: "skill", Icon: Puzzle },
] as const;

export function MonitoringOverview({
  userId,
  userTenant,
  directories,
  canReadInventory,
  scopeLabel,
  range,
  dateControls,
  dateLabel,
}: {
  userId: string;
  userTenant: string;
  directories: Pick<
    ReturnType<typeof useMonitoringDirectories>,
    "tenant" | "scope" | "inventory"
  >;
  canReadInventory: boolean;
  scopeLabel: string;
  range: MonitoringRange | null;
  dateControls: ReactNode;
  dateLabel: ReactNode;
}) {
  const { t, i18n } = useTranslation("common");
  const { tenant, scope, inventory } = directories;
  const selection = agentMonitoringSelection(tenant, range, "");
  const queryKey = ["monitoringOverview", userId, userTenant, selection];
  const agent = useQuery({
    queryKey: [...queryKey, "agent"],
    queryFn: ({ signal }) => getAgentMonitoringTrends(selection!, signal),
    enabled: selection !== null,
  });
  const model = useQuery({
    queryKey: [...queryKey, "model"],
    queryFn: ({ signal }) => getModelMonitoringTrends(selection!, signal),
    enabled: selection !== null,
  });
  const skillSelection = selection && { ...selection, skillId: null };
  const skill = useQuery({
    queryKey: [...queryKey, "skill"],
    queryFn: ({ signal }) => getSkillMonitoringTrends(skillSelection!, signal),
    enabled: skillSelection !== null,
  });
  const today = getMonitoringRange("week", null)![1];
  const skillCountScope =
    tenant === undefined
      ? null
      : {
          tenantId: tenant,
          skillId: null,
          groupIds: [],
          startDate: today,
          endDate: today,
        };
  const skillSummary = useQuery({
    queryKey: [
      "monitoringOverview",
      userId,
      userTenant,
      "skillCount",
      skillCountScope,
    ],
    queryFn: ({ signal }) =>
      getSkillMonitoringSummary(skillCountScope!, signal),
    enabled: skillCountScope !== null,
  });
  const counts = useMemo(
    () =>
      tenant !== undefined && inventory.data
        ? countOverviewResources(inventory.data)
        : undefined,
    [inventory.data, tenant]
  );
  const number = new Intl.NumberFormat(i18n.language);
  const inventoryFailed = scope.isError || inventory.isError;
  const skillCountFailed = scope.isError || skillSummary.isError;
  const skillCount = skillCountFailed
    ? undefined
    : skillSummary.data?.data.current_skill_count;
  const inventoryLoading =
    canReadInventory &&
    !inventoryFailed &&
    (tenant === undefined || inventory.isPending);
  const inventoryState = !canReadInventory
    ? t("ops.noPermission")
    : inventoryFailed
      ? t("ops.loadError")
      : t("common.loading");
  const scopeLoading = Boolean(range && tenant === undefined && !scope.isError);

  return (
    <>
      <h2 className={styles.heading}>{t("ops.monitoring.inventory")}</h2>
      <dl
        className={styles.cards}
        aria-label={t("ops.monitoring.inventory")}
        aria-busy={
          inventoryLoading || inventory.isFetching || skillSummary.isFetching
        }
      >
        {resources.map(({ kind, Icon }) => {
          const connected = kind === "agent" || kind === "model";
          const total =
            kind === "skill"
              ? skillCount
              : connected && canReadInventory && !inventoryFailed
                ? counts?.[kind]
                : undefined;
          const status =
            kind === "skill"
              ? t(skillCountFailed ? "ops.loadError" : "common.loading")
              : connected
                ? inventoryState
                : t("ops.monitoring.notConnected");
          return (
            <div className={styles.card} key={kind}>
              <Icon size={25} className={styles.icon} aria-hidden />
              <div>
                <dt>{t(`ops.monitoring.count.${kind}`)}</dt>
                <dd
                  className={
                    total === undefined ? styles.cardStatus : styles.total
                  }
                >
                  {total !== undefined ? number.format(total) : status}
                </dd>
              </div>
            </div>
          );
        })}
      </dl>

      <h2 className={styles.heading}>{scopeLabel}</h2>
      {dateControls}
      {dateLabel}
      <div className={styles.trends}>
        <OverviewTrend
          title={t("ops.monitoring.overview.agentTrend")}
          trend={{
            points: agent.data?.data.map((day) => ({
              date: day.statistic_date,
              value: day.execution_count,
              coverage: day.coverage_state,
            })),
            publication: agent.data,
            loading:
              scopeLoading ||
              (selection !== null && (agent.isPending || agent.isFetching)),
            failed: scope.isError || agent.isError,
            hasRange: Boolean(range),
          }}
        />
        <OverviewTrend
          title={t("ops.monitoring.overview.modelTrend")}
          trend={{
            points: model.data?.data.map((day) => ({
              date: day.statistic_date,
              value: day.request_count,
            })),
            publication: model.data,
            loading:
              scopeLoading ||
              (selection !== null && (model.isPending || model.isFetching)),
            failed: scope.isError || model.isError,
            hasRange: Boolean(range),
          }}
        />
        <OverviewTrend title={t("ops.monitoring.overview.mcpTrend")} />
        <OverviewTrend
          title={t("ops.monitoring.overview.skillTrend")}
          trend={{
            points: skill.data?.data.map((day) => ({
              date: day.statistic_date,
              value: day.usage_count,
            })),
            loading:
              scopeLoading ||
              (skillSelection !== null &&
                (skill.isPending || skill.isFetching)),
            failed: scope.isError || skill.isError,
            hasRange: Boolean(range),
          }}
        />
      </div>
    </>
  );
}
