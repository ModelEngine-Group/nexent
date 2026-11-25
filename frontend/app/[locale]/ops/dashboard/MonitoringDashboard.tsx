// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  DatePicker,
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
import type { ModelMonitoringSelection } from "@/types/modelMonitoring";
import type { OperationsResource } from "@/types/operations";
import type {
  SkillMonitoringQueryKey,
  SkillMonitoringRow,
  SkillMonitoringSelection,
} from "@/types/skillMonitoring";
import { AgentMonitoringDetails } from "./AgentMonitoringDetails";
import { AgentMonitoringPanels } from "./AgentMonitoringPanels";
import { agentMonitoringSelection } from "./agentMonitoringValues";
import { McpMonitoring } from "./components/mcp/McpMonitoring";
import { ModelMonitoringDetails } from "./components/model/ModelMonitoringDetails";
import { ModelMonitoringPanels } from "./components/model/ModelMonitoringPanels";
import { MonitoringOverview } from "./components/overview/MonitoringOverview";
import { SkillMonitoring } from "./components/skill/SkillMonitoring";
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
  const [modelDrilldown, setModelDrilldown] =
    useState<Pick<OperationsResource, "tenant_id" | "id" | "name">>();
  const [skillDrilldown, setSkillDrilldown] = useState<SkillMonitoringRow>();
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
  const resourceSelection = onOverview ? "" : (filters.resources[tab] ?? "");
  const scopePending = directories.tenant === undefined;
  const models =
    tab === "model" && canReadInventory && !scopePending
      ? directories.inventory.data?.filter((item) => item.kind === "model")
      : undefined;
  const directoryModel = models?.find(
    (item) => resourceKey(item.tenant_id, item.id) === resourceSelection
  );
  const selectedModel =
    directoryModel ??
    (tab === "model" &&
    !scopePending &&
    modelDrilldown &&
    (!directories.tenant || directories.tenant === modelDrilldown.tenant_id) &&
    resourceKey(modelDrilldown.tenant_id, modelDrilldown.id) ===
      resourceSelection
      ? modelDrilldown
      : undefined);
  const resourceQuery =
    tab === "skill" ? directories.skills : directories.inventory;
  const inventoryChoice = (
    item: Pick<OperationsResource, "tenant_id" | "id" | "name">
  ) => ({
    value: resourceKey(item.tenant_id, item.id),
    label: directories.tenant
      ? item.name || String(item.id)
      : `${item.name || item.id} · ${tenantLabel(item.tenant_id)}`,
  });
  const directorySkill = directories.skills.data?.find(
    (item) =>
      resourceKey(directories.tenant ?? "", String(item.skill_id)) ===
      resourceSelection
  );
  const selectedSkill =
    tab === "skill" && !scopePending
      ? directorySkill
        ? {
            skill_id: String(directorySkill.skill_id),
            tenant_id: directories.tenant,
            skill_name: directorySkill.name,
          }
        : skillDrilldown &&
            (!directories.tenant ||
              skillDrilldown.tenant_id === directories.tenant) &&
            resourceKey(
              skillDrilldown.tenant_id ?? "",
              skillDrilldown.skill_id
            ) === resourceSelection
          ? skillDrilldown
          : undefined
      : undefined;
  const directoryChoices =
    tab === "skill"
      ? directories.skills.data?.map((skill) => ({
          value: resourceKey(directories.tenant ?? "", String(skill.skill_id)),
          label: skill.name || skill.skill_id,
        }))
      : canReadInventory
        ? directories.inventory.data
            ?.filter((item) => item.kind === tab)
            .map(inventoryChoice)
        : undefined;
  const resourceChoices =
    selectedModel && !directoryModel
      ? [...(directoryChoices ?? []), inventoryChoice(selectedModel)]
      : selectedSkill && !directorySkill
        ? [
            ...(directoryChoices ?? []),
            {
              value: resourceSelection,
              label: selectedSkill.skill_name || `#${selectedSkill.skill_id}`,
            },
          ]
        : directoryChoices;
  const resource = resourceChoices?.find(
    (choice) => choice.value === resourceSelection
  );
  const allResources = onOverview ? "" : t(`ops.monitoring.all.${tab}`);
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
  const modelSelection: ModelMonitoringSelection | null =
    tab === "model" && directories.tenant !== undefined && range
      ? {
          tenantId: selectedModel?.tenant_id ?? directories.tenant,
          modelId: selectedModel?.id ?? null,
          groupIds: group ? [Number(group)] : [],
          startDate: range[0],
          endDate: range[1],
        }
      : null;
  const modelQueryKey = [
    "modelMonitoring",
    userId,
    userTenant,
    modelSelection,
  ] as const;
  const skillSelection: SkillMonitoringSelection | null =
    tab === "skill" && directories.tenant !== undefined && range
      ? {
          tenantId: selectedSkill?.tenant_id ?? directories.tenant,
          skillId: selectedSkill?.skill_id ?? null,
          groupIds: group ? [Number(group)] : [],
          startDate: range[0],
          endDate: range[1],
        }
      : null;
  const skillQueryKey: SkillMonitoringQueryKey = [
    "skillMonitoring",
    userId,
    userTenant,
    skillSelection,
  ];
  const selectedMonitoringResource =
    selectedAgent ?? selectedModel ?? directories.mcpService;
  const selectedMcpTool = directories.canReadTools
    ? directories.tools.data?.find((tool) => tool.name === filters.tool)
    : undefined;
  const modelFetching = useIsFetching({ queryKey: modelQueryKey }) > 0;
  const skillFetching = useIsFetching({ queryKey: skillQueryKey }) > 0;
  const queryClient = useQueryClient();
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
          loading={
            directories.fetching ||
            agentMonitoring.fetching ||
            modelFetching ||
            skillFetching
          }
          onClick={() => {
            void directories.refresh();
            if (selection) void agentMonitoring.refresh();
            if (modelSelection)
              void queryClient.refetchQueries({
                queryKey: modelQueryKey,
                type: "active",
              });
            if (skillSelection)
              void queryClient.refetchQueries({
                queryKey: skillQueryKey,
                type: "active",
              });
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
                    : tab === "skill" && !directories.tenant && !selectedSkill
                      ? t("ops.monitoring.groupTenantRequired")
                      : tab !== "skill" && !canReadInventory && !selectedModel
                        ? t("ops.noPermission")
                        : undefined
                }
                loading={resourceQuery.isFetching}
                failed={resourceQuery.isError}
                onChange={(value) => dispatch({ type: "resource", tab, value })}
              />
              {directories.mcpService && (
                <DirectorySelect
                  label={t("ops.monitoring.tool")}
                  allLabel={t("ops.monitoring.allTools")}
                  value={selectedMcpTool?.name ?? ""}
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
        <MonitoringOverview
          userId={userId}
          userTenant={userTenant}
          directories={directories}
          canReadInventory={canReadInventory}
          scopeLabel={scopeLabel}
          range={range}
          dateControls={dateControls}
          dateLabel={dateLabel}
        />
      ) : (
        <>
          <h2
            className={styles.sectionHeading}
            ref={resourceHeading}
            tabIndex={-1}
          >
            {selectedMonitoringResource
              ? selectedMonitoringResource.name || selectedMonitoringResource.id
              : (resource?.label ?? allResources)}
            {selectedMcpTool && ` / ${selectedMcpTool.name}`} ·{" "}
            {selectedMonitoringResource
              ? tenantLabel(selectedMonitoringResource.tenant_id)
              : selectedSkill?.tenant_id
                ? tenantLabel(selectedSkill.tenant_id)
                : scopeLabel}
          </h2>
          {dateLabel}
          {tab === "agent" ? (
            <>
              <AgentMonitoringPanels
                data={agentMonitoring}
                tenantLabel={tenantLabel}
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
                hasRange={Boolean(range)}
              />
              <AgentMonitoringDetails
                key={JSON.stringify([filters.tenant, resourceSelection])}
                queryKey={agentMonitoring.queryKey}
                scopeLoading={scopeLoading}
                hasRange={Boolean(range)}
                selectedResource={resource?.value ?? ""}
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
          ) : tab === "model" ? (
            <>
              <ModelMonitoringPanels
                queryKey={modelQueryKey}
                inventory={{
                  count: models
                    ? new Set(
                        models.map((item) =>
                          resourceKey(item.tenant_id, item.id)
                        )
                      ).size
                    : null,
                  loading:
                    canReadInventory &&
                    !models &&
                    !directories.scope.isError &&
                    (scopePending || directories.inventory.isPending),
                  failed:
                    canReadInventory &&
                    (directories.scope.isError ||
                      directories.inventory.isError),
                }}
                singleModel={Boolean(selectedModel)}
                scopeLoading={scopeLoading}
                hasRange={Boolean(range)}
              />
              <ModelMonitoringDetails
                key={JSON.stringify([filters.tenant, resourceSelection])}
                queryKey={modelQueryKey}
                scopeLoading={scopeLoading}
                hasRange={Boolean(range)}
                onViewStatistics={(row) => {
                  setModelDrilldown({
                    tenant_id: row.tenant_id,
                    id: row.model_id,
                    name:
                      row.display_name || row.model_name || `#${row.model_id}`,
                  });
                  dispatch({
                    type: "resource",
                    tab: "model",
                    value: resourceKey(row.tenant_id, row.model_id),
                  });
                  requestAnimationFrame(() => resourceHeading.current?.focus());
                }}
              />
            </>
          ) : tab === "skill" ? (
            <SkillMonitoring
              key={JSON.stringify(skillSelection)}
              queryKey={skillQueryKey}
              singleSkill={Boolean(selectedSkill)}
              scopeLoading={scopeLoading}
              hasRange={Boolean(range)}
              onView={(row) => {
                setSkillDrilldown(row);
                dispatch({
                  type: "resource",
                  tab: "skill",
                  value: resourceKey(row.tenant_id ?? "", row.skill_id),
                });
                requestAnimationFrame(() => resourceHeading.current?.focus());
              }}
            />
          ) : (
            <McpMonitoring
              scope={
                selectedMcpTool
                  ? "tool"
                  : directories.mcpService
                    ? "service"
                    : "all"
              }
            />
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
