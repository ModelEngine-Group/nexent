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
import { useEffect, useReducer, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { hasRole } from "@/lib/roles";
import type {
  McpMonitoringQueryKey,
  McpMonitoringRow,
  McpMonitoringSelection,
  McpServiceFilter,
} from "@/types/mcpMonitoring";
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
import { getMcpDrilldownService } from "./components/mcp/mcpMonitoringValues";
import { ModelMonitoringDetails } from "./components/model/ModelMonitoringDetails";
import { ModelMonitoringPanels } from "./components/model/ModelMonitoringPanels";
import { MonitoringOverview } from "./components/overview/MonitoringOverview";
import { SkillMonitoring } from "./components/skill/SkillMonitoring";
import {
  dateFormat,
  getMonitoringRange,
  getMonitoringToday,
  initialMonitoringFilters,
  matchesGroupScope,
  maxRangeDays,
  monitoringTabs,
  UNGROUPED_GROUP,
  updateMonitoringFilters,
  type DatePreset,
  type MonitoringTab,
} from "./monitoringFilters";
import {
  mcpServiceKey,
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
  const [mcpDrilldown, setMcpDrilldown] = useState<{
    tenantId: string;
    service: McpServiceFilter;
    toolName?: string;
  }>();
  const directories = useMonitoringDirectories({
    userId,
    userTenant,
    canChooseTenant,
    canReadInventory,
    selectedTenant: filters.tenant,
    tab,
    selectedService: filters.resources.mcp,
    resourceGroup: tab === "mcp" ? filters.group : "",
    drilledMcpService: mcpDrilldown,
  });

  const tenantChoices =
    directories.tenants.data?.map((tenant) => ({
      value: tenant.tenant_id,
      label:
        tenant.tenant_name?.trim() || t("ops.monitoring.tenantNameUnavailable"),
    })) ?? [];
  const tenantLabel = (id: string) =>
    tenantChoices.find((choice) => choice.value === id)?.label ??
    t(
      directories.tenants.isPending
        ? "common.loading"
        : "ops.monitoring.tenantNameUnavailable"
    );
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
      onChange={(value) => {
        setMcpDrilldown(undefined);
        dispatch({ type: "tenant", value });
      }}
    />
  ) : (
    <Select
      aria-label={t("ops.tenant")}
      className={styles.select}
      disabled
      loading={directories.tenants.isFetching}
      status={directories.tenants.isError ? "error" : undefined}
      value={userTenant}
      options={[{ value: userTenant, label: tenantLabel(userTenant) }]}
    />
  );

  const onOverview = tab === "overview";
  const resourceSelection = onOverview ? "" : (filters.resources[tab] ?? "");
  const scopePending = directories.tenant === undefined;
  const group =
    tab !== "model" && tab !== "overview" && directories.tenant
      ? filters.group
      : "";
  const inGroupScope = (groupIds: readonly number[] | null | undefined) =>
    matchesGroupScope(groupIds, group);
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
    tab === "skill"
      ? directories.skills
      : tab === "mcp"
        ? directories.mcpCatalog
        : directories.inventory;
  const inventoryChoice = (
    item: Pick<OperationsResource, "tenant_id" | "id" | "name">
  ) => ({
    value: resourceKey(item.tenant_id, item.id),
    label: directories.tenant
      ? item.name || String(item.id)
      : `${item.name || item.id} · ${tenantLabel(item.tenant_id)}`,
  });
  const scopedSkills = directories.skills.data?.filter((skill) =>
    inGroupScope(skill.source === "official" ? null : skill.group_ids)
  );
  const directorySkill = scopedSkills?.find(
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
        : !group &&
            skillDrilldown &&
            (!directories.tenant ||
              skillDrilldown.tenant_id === directories.tenant) &&
            resourceKey(
              skillDrilldown.tenant_id ?? "",
              skillDrilldown.skill_id
            ) === resourceSelection
          ? skillDrilldown
          : undefined
      : undefined;
  const mcpService = directories.mcpService;
  const mcpServices: McpServiceFilter[] = [...(directories.mcpServices ?? [])];
  if (
    mcpService &&
    !mcpServices.some((service) => mcpServiceKey(service) === resourceSelection)
  ) {
    mcpServices.push(mcpService);
  }
  const directoryChoices =
    tab === "skill"
      ? scopedSkills?.map((skill) => ({
          value: resourceKey(directories.tenant ?? "", String(skill.skill_id)),
          label: skill.name || skill.skill_id,
        }))
      : tab === "mcp"
        ? mcpServices.map((service) => {
            const tenant = directories.mcpServiceTenant(service);
            return {
              value: mcpServiceKey(service),
              label:
                !directories.tenant && tenant
                  ? `${service.name} · ${tenantLabel(tenant)}`
                  : service.name,
            };
          })
        : canReadInventory
          ? directories.inventory.data
              ?.filter(
                (item) => item.kind === tab && inGroupScope(item.group_ids)
              )
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
  useEffect(() => {
    if (
      tab !== "overview" &&
      group &&
      resourceSelection &&
      resourceQuery.isSuccess &&
      !resource
    ) {
      dispatch({ type: "resource", tab, value: "" });
    }
  }, [tab, group, resourceSelection, resourceQuery.isSuccess, resource]);

  const allResources = onOverview ? "" : t(`ops.monitoring.all.${tab}`);
  const scopeDisabledText = directories.scope.isError
    ? t("ops.loadError")
    : t("common.loading");

  const range = getMonitoringRange(filters.datePreset, filters.customRange);
  const agents =
    tab === "agent" && canReadInventory
      ? directories.inventory.data?.filter(
          (item) => item.kind === "agent" && inGroupScope(item.group_ids)
        )
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
          groupIds: [],
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
          groupIds: [],
          ...(group ? { resourceGroup: group } : {}),
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
  const selectedMonitoringResource = selectedAgent ?? selectedModel;
  const mcpTenant = mcpService && directories.mcpServiceTenant(mcpService);
  const resourceTenant =
    selectedMonitoringResource?.tenant_id ??
    selectedSkill?.tenant_id ??
    mcpTenant;
  const availableMcpTools = directories.canReadTools
    ? (directories.tools.data ?? [])
    : [];
  const drilledToolName =
    mcpDrilldown &&
    mcpService &&
    mcpDrilldown.tenantId === mcpTenant &&
    mcpServiceKey(mcpDrilldown.service) === resourceSelection &&
    mcpDrilldown.toolName === filters.tool
      ? mcpDrilldown.toolName
      : undefined;
  const selectedMcpTool =
    availableMcpTools.find((tool) => tool.name === filters.tool)?.name ??
    drilledToolName;
  const toolChoices = availableMcpTools.map(({ name }) => ({
    value: name,
    label: name,
  }));
  if (
    drilledToolName &&
    !toolChoices.some(({ value }) => value === drilledToolName)
  ) {
    toolChoices.push({ value: drilledToolName, label: drilledToolName });
  }
  const mcpSelection: McpMonitoringSelection | null =
    tab === "mcp" &&
    directories.tenant !== undefined &&
    range &&
    (!resourceSelection || mcpService || directories.mcpCatalog.isSuccess)
      ? {
          tenantId: directories.tenant,
          groupIds: [],
          ...(group ? { resourceGroup: group } : {}),
          serviceId: mcpService?.service_id ?? null,
          serverType: mcpService?.service_id === null ? mcpService.type : null,
          toolName: selectedMcpTool ?? null,
          startDate: range[0],
          endDate: range[1],
        }
      : null;
  const mcpQueryKey: McpMonitoringQueryKey = [
    "mcpMonitoring",
    userId,
    userTenant,
    mcpSelection,
  ];
  const mcpFetching = useIsFetching({ queryKey: mcpQueryKey }) > 0;
  const modelFetching = useIsFetching({ queryKey: modelQueryKey }) > 0;
  const skillFetching = useIsFetching({ queryKey: skillQueryKey }) > 0;
  const queryClient = useQueryClient();
  const scopeLoading = Boolean(
    range && scopePending && !directories.scope.isError
  );
  const resourceHeading = useRef<HTMLHeadingElement>(null);
  const viewMcpStatistics = (row: McpMonitoringRow) => {
    const service = getMcpDrilldownService(row);
    if (!service || (!canChooseTenant && row.tenant_id !== directories.tenant))
      return;
    setMcpDrilldown({
      tenantId: row.tenant_id,
      service,
      toolName: row.tool_name,
    });
    if (directories.tenant !== row.tenant_id) {
      dispatch({ type: "tenant", value: row.tenant_id });
    }
    dispatch({ type: "resource", tab: "mcp", value: mcpServiceKey(service) });
    dispatch({ type: "tool", value: row.tool_name ?? "" });
    requestAnimationFrame(() => resourceHeading.current?.focus());
  };
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
          date.format(dateFormat) > getMonitoringToday() ||
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
            skillFetching ||
            mcpFetching
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
            if (mcpSelection)
              void queryClient.refetchQueries({
                queryKey: mcpQueryKey,
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
      ((tab !== "model" && directories.groups.isError) ||
        resourceQuery.isError ||
        directories.tools.isError));

  const content = (
    <>
      <div className={styles.filters}>
        <div className={styles.scopeControls}>
          {tenantSelect}
          {!onOverview && (
            <>
              {tab !== "model" && (
                <DirectorySelect
                  label={t("ops.monitoring.group")}
                  allLabel={t("ops.monitoring.allGroups")}
                  value={group}
                  choices={[
                    ...(directories.groups.data?.groups.map((group) => ({
                      value: String(group.group_id),
                      label: group.group_name,
                    })) ?? []),
                    {
                      value: UNGROUPED_GROUP,
                      label: t("ops.monitoring.ungrouped"),
                    },
                  ]}
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
              )}
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
                      : tab !== "skill" &&
                          tab !== "mcp" &&
                          !canReadInventory &&
                          !selectedModel
                        ? t("ops.noPermission")
                        : undefined
                }
                loading={resourceQuery.isFetching}
                failed={resourceQuery.isError}
                onChange={(value) => dispatch({ type: "resource", tab, value })}
              />
              {mcpService && (
                <DirectorySelect
                  label={t("ops.monitoring.tool")}
                  allLabel={t("ops.monitoring.allTools")}
                  value={selectedMcpTool ?? ""}
                  choices={toolChoices}
                  disabledText={
                    directories.canReadTools || drilledToolName
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
              : (mcpService?.name ?? resource?.label ?? allResources)}
            {selectedMcpTool && ` / ${selectedMcpTool}`} ·{" "}
            {resourceTenant ? tenantLabel(resourceTenant) : scopeLabel}
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
              scope={selectedMcpTool ? "tool" : mcpService ? "service" : "all"}
              queryKey={mcpQueryKey}
              viewKey={JSON.stringify([
                directories.tenant,
                mcpService ? mcpServiceKey(mcpService) : "",
                selectedMcpTool,
              ])}
              onViewStatistics={viewMcpStatistics}
              registeredServices={{
                count: directories.mcpServiceCount ?? null,
                loading:
                  (scopePending && !directories.scope.isError) ||
                  directories.mcpCatalog.isLoading,
              }}
              scopeLoading={scopeLoading}
              hasRange={Boolean(range)}
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
