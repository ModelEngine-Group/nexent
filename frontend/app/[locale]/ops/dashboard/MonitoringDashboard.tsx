// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import {
  Alert,
  Button,
  DatePicker,
  Empty,
  Segmented,
  Select,
  Spin,
  Tabs,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { RefreshCw } from "lucide-react";
import { useReducer, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { hasRole } from "@/lib/roles";
import { AgentMonitoringDetails } from "./AgentMonitoringDetails";
import { AgentMonitoringPanels } from "./AgentMonitoringPanels";
import { agentMonitoringSelection } from "./agentMonitoringValues";
import {
  dateFormat,
  getMonitoringRange,
  initialMonitoringFilters,
  maxRangeDays,
  monitoringTabs,
  updateMonitoringFilters,
  type DatePreset,
  type MonitoringTab,
} from "./monitoringFilters";
import {
  resourceKey,
  useMonitoringDirectories,
} from "./useMonitoringDirectories";
import styles from "./monitoring.module.css";
import { useAgentMonitoring } from "./useAgentMonitoring";

interface Choice {
  value: string;
  label: string;
}

function DirectorySelect({
  label,
  allLabel,
  value,
  choices = [],
  onChange,
  disabledText,
  loading,
  failed,
}: {
  label: string;
  allLabel: string;
  value: string;
  choices?: Choice[];
  onChange: (value: string) => void;
  disabledText?: string;
  loading?: boolean;
  failed?: boolean;
}) {
  const { t } = useTranslation("common");
  return (
    <Select
      aria-label={label}
      className={styles.select}
      disabled={Boolean(disabledText)}
      status={failed ? "error" : undefined}
      loading={loading}
      showSearch={{ optionFilterProp: "label" }}
      value={disabledText ? undefined : value}
      onChange={onChange}
      placeholder={disabledText}
      options={[
        { value: "", label: allLabel },
        ...choices,
        ...(!choices.length && !loading && !failed
          ? [{ value: "#empty", label: t("ops.empty"), disabled: true }]
          : []),
      ]}
    />
  );
}

function MonitoringScope({
  userId,
  userTenant,
  canChooseTenant,
  canReadInventory,
}: {
  userId: string;
  userTenant: string;
  canChooseTenant: boolean;
  canReadInventory: boolean;
}) {
  const { t } = useTranslation("common");
  const [tab, setTab] = useState<MonitoringTab>("overview");
  const [filters, dispatch] = useReducer(
    updateMonitoringFilters,
    initialMonitoringFilters
  );
  const directories = useMonitoringDirectories({
    userId,
    userTenant,
    canChooseTenant,
    canReadInventory,
    selectedTenant: filters.tenant,
    tab,
    selectedService: filters.resources.mcp,
  });

  const tenantChoices =
    directories.tenants.data?.map((tenant) => ({
      value: tenant.tenant_id,
      label: tenant.tenant_name || tenant.tenant_id,
    })) ?? [];
  const tenantLabel = (id: string) =>
    tenantChoices.find((choice) => choice.value === id)?.label ?? id;
  const visibleTenant =
    directories.tenant === undefined
      ? canChooseTenant
        ? filters.tenant
        : userTenant
      : directories.tenant;
  const scopeLabel = visibleTenant
    ? tenantLabel(visibleTenant)
    : t("ops.allTenants");
  const tenantSelect = canChooseTenant ? (
    <DirectorySelect
      label={t("ops.tenant")}
      allLabel={t("ops.allTenants")}
      value={filters.tenant}
      choices={tenantChoices}
      loading={directories.tenants.isFetching}
      failed={directories.tenants.isError}
      onChange={(value) => dispatch({ type: "tenant", value })}
    />
  ) : (
    <Select
      aria-label={t("ops.tenant")}
      className={styles.select}
      disabled
      value={userTenant}
      options={[{ value: userTenant, label: userTenant }]}
    />
  );

  const onOverview = tab === "overview";
  const resourceQuery =
    tab === "skill" ? directories.skills : directories.inventory;
  const resourceChoices =
    tab === "skill"
      ? directories.skills.data?.map((skill) => ({
          value: resourceKey(directories.tenant ?? "", skill.skill_id),
          label: skill.name || skill.skill_id,
        }))
      : directories.inventory.data
          ?.filter((item) => item.kind === tab)
          .map((item) => ({
            value: resourceKey(item.tenant_id, item.id),
            label: directories.tenant
              ? item.name || String(item.id)
              : `${item.name || item.id} · ${tenantLabel(item.tenant_id)}`,
          }));
  const resourceSelection = onOverview ? "" : (filters.resources[tab] ?? "");
  const resource = resourceChoices?.find(
    (choice) => choice.value === resourceSelection
  );
  const allResources = onOverview ? "" : t(`ops.monitoring.all.${tab}`);
  const scopePending = directories.tenant === undefined;
  const scopeDisabledText = directories.scope.isError
    ? t("ops.loadError")
    : t("common.loading");

  const range = getMonitoringRange(filters.datePreset, filters.customRange);
  const group = directories.groups.data?.groups.some(
    (item) => String(item.group_id) === filters.group
  )
    ? filters.group
    : "";
  const agents =
    tab === "agent" && canReadInventory
      ? directories.inventory.data?.filter((item) => item.kind === "agent")
      : undefined;
  const selectedAgent = agents?.find(
    (item) => resourceKey(item.tenant_id, item.id) === resourceSelection
  );
  const selection =
    tab === "agent"
      ? agentMonitoringSelection(
          directories.tenant,
          range,
          group,
          selectedAgent
        )
      : null;
  const agentMonitoring = useAgentMonitoring(userId, userTenant, selection);
  const scopeLoading = Boolean(
    range && scopePending && !directories.scope.isError
  );
  const resourceHeading = useRef<HTMLHeadingElement>(null);
  const dateControls = (
    <div className={styles.dateControls}>
      <Segmented<DatePreset>
        aria-label={t("ops.monitoring.date")}
        className={styles.datePreset}
        value={filters.datePreset}
        options={[
          { value: "week", label: t("ops.monitoring.week") },
          { value: "month", label: t("ops.monitoring.month") },
          { value: "custom", label: t("ops.monitoring.custom") },
        ]}
        onChange={(value) => dispatch({ type: "datePreset", value })}
      />
      <DatePicker.RangePicker
        className={styles.datePicker}
        id={{ start: "monitoring-date-start", end: "monitoring-date-end" }}
        placeholder={[
          t("ops.monitoring.startDate"),
          t("ops.monitoring.endDate"),
        ]}
        format={dateFormat}
        disabled={filters.datePreset !== "custom"}
        allowEmpty={
          filters.datePreset === "custom" ? [false, false] : [true, true]
        }
        value={
          filters.datePreset === "custom" && range
            ? [dayjs(range[0]), dayjs(range[1])]
            : null
        }
        disabledDate={(date, { from }) =>
          Boolean(
            from &&
            Math.abs(date.startOf("day").diff(from.startOf("day"), "day")) >=
              maxRangeDays
          )
        }
        onChange={(dates, values) =>
          dispatch({
            type: "customRange",
            value: dates?.[0] && dates[1] ? values : null,
          })
        }
      />
      {!onOverview && (
        <Button
          icon={<RefreshCw size={15} aria-hidden />}
          loading={directories.fetching || agentMonitoring.fetching}
          onClick={() => {
            void directories.refresh();
            if (selection) void agentMonitoring.refresh();
          }}
        >
          {t("common.refresh")}
        </Button>
      )}
    </div>
  );
  const dateLabel = (
    <p className={styles.dateLabel} aria-live="polite">
      {range ? range.join(" – ") : t("ops.monitoring.chooseRange")}
    </p>
  );
  const directoryFailed =
    directories.scope.isError ||
    directories.tenants.isError ||
    (!onOverview &&
      (directories.groups.isError ||
        resourceQuery.isError ||
        directories.tools.isError));
  const placeholder = (
    <div className={styles.placeholder}>
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t("ops.monitoring.statisticsUnavailable")}
      />
    </div>
  );

  const content = (
    <>
      <div className={styles.filters}>
        <div className={styles.scopeControls}>
          {tenantSelect}
          {!onOverview && (
            <>
              <DirectorySelect
                label={t("ops.monitoring.group")}
                allLabel={t("ops.monitoring.allGroups")}
                value={group}
                choices={directories.groups.data?.groups.map((group) => ({
                  value: String(group.group_id),
                  label: group.group_name,
                }))}
                disabledText={
                  scopePending
                    ? scopeDisabledText
                    : !directories.tenant
                      ? t("ops.monitoring.groupTenantRequired")
                      : undefined
                }
                loading={directories.groups.isFetching}
                failed={directories.groups.isError}
                onChange={(value) => dispatch({ type: "group", value })}
              />
              <DirectorySelect
                label={t(`ops.monitoring.tab.${tab}`)}
                allLabel={allResources}
                value={resource?.value ?? ""}
                choices={resourceChoices}
                disabledText={
                  scopePending
                    ? scopeDisabledText
                    : tab === "skill" && !directories.tenant
                      ? t("ops.monitoring.notConnected")
                      : tab !== "skill" && !canReadInventory
                        ? t("ops.noPermission")
                        : undefined
                }
                loading={resourceQuery.isFetching}
                failed={resourceQuery.isError}
                onChange={(value) => dispatch({ type: "resource", tab, value })}
              />
              {tab === "mcp" && resource && (
                <DirectorySelect
                  label={t("ops.monitoring.tool")}
                  allLabel={t("ops.monitoring.allTools")}
                  value={
                    directories.tools.data?.some(
                      (tool) => tool.name === filters.tool
                    )
                      ? filters.tool
                      : ""
                  }
                  choices={directories.tools.data?.map((tool) => ({
                    value: tool.name,
                    label: tool.name,
                  }))}
                  disabledText={
                    directories.canReadTools
                      ? undefined
                      : t("ops.monitoring.notConnected")
                  }
                  loading={directories.tools.isFetching}
                  failed={directories.tools.isError}
                  onChange={(value) => dispatch({ type: "tool", value })}
                />
              )}
            </>
          )}
        </div>
        {!onOverview && dateControls}
      </div>
      {directoryFailed && (
        <Alert type="error" title={t("ops.loadError")} showIcon />
      )}
      {onOverview ? (
        <>
          <h2 className={styles.sectionHeading}>
            {t("ops.monitoring.inventory")}
          </h2>
          <dl className={styles.inventory}>
            {(["agent", "model", "mcp", "skill"] as const).map((key) => (
              <div key={key}>
                <dt>{t(`ops.monitoring.count.${key}`)}</dt>
                <dd aria-label={t("ops.monitoring.notConnected")}>—</dd>
              </div>
            ))}
          </dl>
          <h2 className={styles.sectionHeading}>{scopeLabel}</h2>
          {dateControls}
          {dateLabel}
          {placeholder}
        </>
      ) : (
        <>
          <h2
            className={styles.sectionHeading}
            ref={resourceHeading}
            tabIndex={-1}
          >
            {selectedAgent
              ? selectedAgent.name || selectedAgent.id
              : (resource?.label ?? allResources)}{" "}
            ·{" "}
            {selectedAgent ? tenantLabel(selectedAgent.tenant_id) : scopeLabel}
          </h2>
          {dateLabel}
          {tab === "agent" ? (
            <>
              <AgentMonitoringPanels
                data={agentMonitoring}
                inventory={{
                  count: agents
                    ? new Set(
                        agents.map((item) =>
                          resourceKey(item.tenant_id, item.id)
                        )
                      ).size
                    : null,
                  loading:
                    canReadInventory &&
                    !agents &&
                    (directories.inventory.isFetching ||
                      (scopePending && !directories.scope.isError)),
                  failed: canReadInventory && directories.inventory.isError,
                }}
                singleAgent={Boolean(selectedAgent)}
                scopeLoading={scopeLoading}
                hasSelection={Boolean(selection)}
                hasRange={Boolean(range)}
              />
              <AgentMonitoringDetails
                key={JSON.stringify(selection)}
                queryKey={agentMonitoring.queryKey}
                scopeLoading={scopeLoading}
                hasRange={Boolean(range)}
                selectedResource={resource?.value ?? ""}
                tenantLabel={tenantLabel}
                inventory={directories.inventory.data}
                canViewStatistics={(key) =>
                  agents?.some(
                    (item) => resourceKey(item.tenant_id, item.id) === key
                  ) ?? false
                }
                onViewStatistics={(value) => {
                  dispatch({ type: "resource", tab: "agent", value });
                  requestAnimationFrame(() => resourceHeading.current?.focus());
                }}
              />
            </>
          ) : (
            placeholder
          )}
        </>
      )}
    </>
  );

  return (
    <section className={styles.dashboard}>
      <Typography.Title level={1} className={styles.title}>
        {t("ops.monitoring.title")}
      </Typography.Title>
      <Tabs
        activeKey={tab}
        onChange={(key) => setTab(key as MonitoringTab)}
        items={monitoringTabs.map((key) => ({
          key,
          label: t(`ops.monitoring.tab.${key}`),
          children: key === tab ? content : undefined,
        }))}
      />
    </section>
  );
}

export function MonitoringDashboard() {
  const { t } = useTranslation("common");
  const { user, hasPermission, isLoading } = useAuthorizationContext();
  const canChooseTenant = hasRole(user, "SU");
  if (isLoading)
    return (
      <Spin className={styles.authLoading} aria-label={t("common.loading")} />
    );
  if (
    !user ||
    !(canChooseTenant || (hasRole(user, "OPS") && user.tenantId)) ||
    !hasPermission("ops.dashboard:read")
  ) {
    return (
      <Alert
        className={styles.authLoading}
        type="warning"
        title={t("ops.noPermission")}
      />
    );
  }
  return (
    <MonitoringScope
      key={JSON.stringify([user.id, user.tenantId, canChooseTenant])}
      userId={user.id}
      userTenant={user.tenantId ?? ""}
      canChooseTenant={canChooseTenant}
      canReadInventory={hasPermission("resource.inventory:read")}
    />
  );
}
