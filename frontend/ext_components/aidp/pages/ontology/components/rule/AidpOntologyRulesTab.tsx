// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Checkbox,
  Dropdown,
  Empty,
  Input,
  Popover,
  Skeleton,
  Switch,
  Table,
  Tooltip,
  type TableColumnsType,
} from "antd";
import {
  QuestionCircleOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
} from "@ant-design/icons";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import { ruleOperatorLabel } from "@/ext_components/aidp/shared/utils/aidpOntologyRule";
import { formatAidpDateTime } from "@/ext_components/aidp/shared/utils/aidpTime";
import AidpResizableTitle, {
  type AidpResizableTitleProps,
} from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import { AIDP_MIN_COLUMN_WIDTH } from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";
import { useAidpOntologyColumnWidths } from "@/ext_components/aidp/shared/hooks/useAidpOntologyColumnWidths";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type {
  AidpOntologyRule,
  AidpOntologyRulePayload,
} from "@/ext_components/aidp/shared/types/ontology";
import styles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import AidpOntologyRuleDrawer from "./AidpOntologyRuleDrawer";
import AidpOntologyRuleDetailDrawer from "./AidpOntologyRuleDetailDrawer";
import ruleStyles from "./AidpOntologyRulesTab.module.css";

interface AidpOntologyRulesTabProps {
  domainId: string;
}

const MANAGER_ROLES = new Set(["SU", "ADMIN", "SPEED", "ASSET_OWNER"]);
const RULE_LIMIT = 100;

const toPayload = (rule: AidpOntologyRule): AidpOntologyRulePayload => ({
  name: rule.name,
  description: rule.description,
  enabled: rule.enabled,
  condition: rule.condition,
  action: rule.action,
});

const AidpOntologyRulesTab: React.FC<AidpOntologyRulesTabProps> = ({
  domainId,
}) => {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const scope = useAidpQueryScope();
  const queryClient = useQueryClient();
  const { user, isAuthzReady } = useAuthorizationContext();
  const canManage = !!user && MANAGER_ROLES.has(user.role) && isAuthzReady;
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [search, setSearch] = useState("");
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [visibleColumns, setVisibleColumns] = useState({
    description: true,
    createTime: true,
    updateTime: true,
  });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailRule, setDetailRule] = useState<AidpOntologyRule | null>(null);
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [togglingRuleId, setTogglingRuleId] = useState<string | null>(null);

  const queryKey = useMemo(
    () => [...scope.key, "ontology-rules", domainId],
    [domainId, scope.key]
  );
  const query = useQuery({
    queryKey,
    // AIDP caps rules at 100 per domain, so one request fetches the full list.
    queryFn: () => aidpOntologyService.listRules(domainId, 1, RULE_LIMIT),
    enabled: scope.enabled && !!domainId,
    staleTime: 0,
    retry: false,
  });
  const countQuery = useQuery({
    queryKey: [...scope.key, "ontology-rule-count", domainId],
    queryFn: () => aidpOntologyService.countRules(domainId),
    enabled: scope.enabled && !!domainId,
    staleTime: 0,
    retry: false,
  });

  const rules = useMemo(() => query.data?.value ?? [], [query.data?.value]);
  const count = countQuery.data?.count;
  const atLimit = (count ?? 0) >= RULE_LIMIT;
  const filteredRules = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return rules;
    return rules.filter((rule) => rule.name.toLowerCase().includes(needle));
  }, [rules, search]);
  const total = filteredRules.length;
  // Keep the rendered page inside range after filtering or deletion shrinks
  // the list without storing a derived value back into state.
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.min(page, lastPage);
  const pagedRules = useMemo(
    () =>
      filteredRules.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    [currentPage, filteredRules, pageSize]
  );
  const selectedRules = rules.filter((rule) =>
    selectedKeys.includes(rule.rule_id)
  );
  const errorMessage = query.error
    ? getAidpErrorMessage(
        query.error,
        t,
        t("aidpKnowledge.ontologyRulesLoadFailed")
      )
    : undefined;

  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-rules", domainId],
    });
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-rule-count", domainId],
    });
  };

  const openCreate = () => {
    setEditingRuleId(null);
    setDrawerOpen(true);
  };

  const openEdit = (rule: AidpOntologyRule) => {
    setDetailRule(null);
    setEditingRuleId(rule.rule_id);
    setDrawerOpen(true);
  };

  const handleToggle = async (rule: AidpOntologyRule, enabled: boolean) => {
    setTogglingRuleId(rule.rule_id);
    try {
      // PATCH is documented as a full overwrite, so read the complete rule and
      // send every field back instead of only {enabled}.
      const detail = await aidpOntologyService.getRule(domainId, rule.rule_id);
      const payload = { ...toPayload(detail), enabled };
      await aidpOntologyService.updateRule(domainId, rule.rule_id, payload);
      message.success(
        enabled
          ? t("aidpKnowledge.ontologyRulesEnabledDone")
          : t("aidpKnowledge.ontologyRulesDisabledDone")
      );
      refresh();
    } catch (error) {
      message.error(
        getAidpErrorMessage(
          error,
          t,
          t("aidpKnowledge.ontologyRulesToggleFailed")
        )
      );
    } finally {
      setTogglingRuleId(null);
    }
  };

  const handleDelete = (rule: AidpOntologyRule) => {
    modal.confirm({
      title: t("aidpKnowledge.ontologyRulesDeleteTitleFixed"),
      content: (
        <div className={ruleStyles.confirmBody}>
          <p>
            {t("aidpKnowledge.ontologyRulesDeleteContentWithName", {
              name: rule.name,
            })}
          </p>
          <p>{t("aidpKnowledge.ontologyRulesDeleteIrreversible")}</p>
        </div>
      ),
      width: 480,
      okText: t("aidpKnowledge.ontologyDelete"),
      cancelText: t("common.cancel"),
      centered: true,
      onOk: async () => {
        try {
          await aidpOntologyService.deleteRule(domainId, rule.rule_id);
          message.success(t("aidpKnowledge.ontologyRulesDeleted"));
          refresh();
        } catch (error) {
          message.error(
            getAidpErrorMessage(
              error,
              t,
              t("aidpKnowledge.ontologyRulesDeleteFailed")
            )
          );
          throw error;
        }
      },
    });
  };

  const handleBatchDelete = () => {
    if (selectedRules.length === 0) {
      message.warning(t("aidpKnowledge.ontologyRulesSelectRequired"));
      return;
    }
    modal.confirm({
      title: t("aidpKnowledge.ontologyRulesBatchDeleteTitle", {
        count: selectedRules.length,
      }),
      content: (
        <div className={ruleStyles.confirmBody}>
          <p>{t("aidpKnowledge.ontologyRulesBatchDeleteContent")}</p>
        </div>
      ),
      width: 520,
      okText: t("aidpKnowledge.ontologyDelete"),
      cancelText: t("common.cancel"),
      centered: true,
      onOk: async () => {
        const outcomes = await Promise.allSettled(
          selectedRules.map((rule) =>
            aidpOntologyService.deleteRule(domainId, rule.rule_id)
          )
        );
        const failed = outcomes.filter(
          (outcome) => outcome.status === "rejected"
        ).length;
        if (failed > 0) {
          message.warning(
            t("aidpKnowledge.ontologyRulesBatchDeletePartial", {
              count: failed,
            })
          );
        } else {
          message.success(t("aidpKnowledge.ontologyRulesDeleted"));
        }
        setSelectedKeys([]);
        refresh();
      },
    });
  };

  const renderConditions = (rule: AidpOntologyRule) => {
    const conditions = rule.condition?.value?.conditions ?? [];
    if (conditions.length === 0) {
      return <span className={ruleStyles.muted}>—</span>;
    }
    return (
      <Popover
        trigger="hover"
        placement="topLeft"
        content={
          <div className={ruleStyles.conditionList}>
            {conditions.map((condition, index) => (
              <div key={`${condition.field}-${index}`}>
                {condition.field}: {ruleOperatorLabel(condition.operator, t)}
                {condition.value !== undefined &&
                condition.value !== null &&
                condition.value !== ""
                  ? `: ${condition.value}`
                  : ""}
              </div>
            ))}
          </div>
        }
      >
        <span className={ruleStyles.countTrigger}>
          {t("aidpKnowledge.ontologyRulesConditionCount", {
            count: conditions.length,
          })}
        </span>
      </Popover>
    );
  };

  const columnTitle = (label: string, help: string) => (
    <span className={ruleStyles.columnTitle}>
      {label}
      <Tooltip title={help}>
        <QuestionCircleOutlined className={ruleStyles.columnHelp} />
      </Tooltip>
    </span>
  );

  const columns: TableColumnsType<AidpOntologyRule> = [
    {
      title: t("aidpKnowledge.ontologyRulesName"),
      dataIndex: "name",
      key: "name",
      width: 180,
      ellipsis: true,
      render: (value: string, record) => (
        <button
          type="button"
          className={ruleStyles.nameLink}
          onClick={() => setDetailRule(record)}
        >
          {value || "—"}
        </button>
      ),
    },
    ...(visibleColumns.description
      ? [
          {
            title: t("aidpKnowledge.ontologyRulesDescription"),
            dataIndex: "description",
            key: "description",
            ellipsis: true,
            render: (value: string) => value || "—",
          },
        ]
      : []),
    {
      title: columnTitle(
        t("aidpKnowledge.ontologyRulesEnabled"),
        t("aidpKnowledge.ontologyRulesEnabledHint")
      ),
      dataIndex: "enabled",
      key: "enabled",
      width: 110,
      render: (enabled: boolean, record) => (
        <Switch
          checked={enabled}
          size="small"
          loading={togglingRuleId === record.rule_id}
          disabled={!canManage}
          onChange={(checked) => void handleToggle(record, checked)}
        />
      ),
    },
    {
      title: columnTitle(
        t("aidpKnowledge.ontologyRulesCandidateRules"),
        t("aidpKnowledge.ontologyRulesCandidateHint")
      ),
      key: "conditions",
      width: 120,
      render: (_value: unknown, record) => renderConditions(record),
    },
    {
      title: columnTitle(
        t("aidpKnowledge.ontologyRulesAggregation"),
        t("aidpKnowledge.ontologyRulesAggregationColumnHint")
      ),
      key: "aggregation",
      width: 120,
      render: (_value: unknown, record) =>
        record.action?.value?.effect_mode === "add"
          ? t("aidpKnowledge.ontologyRulesAddShort")
          : t("aidpKnowledge.ontologyRulesMultiplyShort"),
    },
    {
      title: columnTitle(
        t("aidpKnowledge.ontologyRulesActionCoefficient"),
        t("aidpKnowledge.ontologyRulesCoefficientColumnHint")
      ),
      key: "coefficient",
      width: 130,
      render: (_value: unknown, record) =>
        record.action?.value?.coefficient !== undefined &&
        record.action?.value?.coefficient !== null
          ? t("aidpKnowledge.ontologyRulesFixedCoefficientShort")
          : t("aidpKnowledge.ontologyRulesFieldDerivedShort"),
    },
    ...(visibleColumns.createTime
      ? [
          {
            title: t("aidpKnowledge.ontologyMetadataColumnCreateTime"),
            key: "created_at",
            width: 170,
            render: (_value: unknown, record: AidpOntologyRule) => (
              <span>{formatAidpDateTime(record.created_at)}</span>
            ),
          },
        ]
      : []),
    ...(visibleColumns.updateTime
      ? [
          {
            title: t("aidpKnowledge.ontologyMetadataColumnUpdateTime"),
            key: "updated_at",
            width: 170,
            render: (_value: unknown, record: AidpOntologyRule) => (
              <span>{formatAidpDateTime(record.updated_at)}</span>
            ),
          },
        ]
      : []),
    {
      title: t("aidpKnowledge.ontologyColumnActions"),
      key: "actions",
      width: 130,
      fixed: "right",
      render: (_value, record) => (
        <div className={styles.rowActions}>
          <Button
            type="link"
            size="small"
            disabled={!canManage}
            onClick={() => openEdit(record)}
          >
            {t("aidpKnowledge.ontologyEdit")}
          </Button>
          <Button
            type="link"
            size="small"
            disabled={!canManage}
            onClick={() => handleDelete(record)}
          >
            {t("aidpKnowledge.ontologyDelete")}
          </Button>
        </div>
      ),
    },
  ];

  const columnKeys = columns.map((column) => String(column.key));
  const { tableContainer, columnWidths, totalWidth, handleResize } =
    useAidpOntologyColumnWidths(columnKeys, {
      name: 1.2,
      description: 1.5,
      enabled: 1.1,
      conditions: 1.5,
      aggregation: 1.2,
      coefficient: 1.2,
      created_at: 1.8,
      updated_at: 1.8,
      actions: 1.0,
    });
  const resizableColumns = columns.map((column, index) => {
    const key = columnKeys[index];
    const nextKey = columnKeys[index + 1];
    return {
      ...column,
      width: columnWidths[key],
      onHeaderCell: () =>
        ({
          width: columnWidths[key],
          maxWidth: nextKey
            ? columnWidths[key] + columnWidths[nextKey] - AIDP_MIN_COLUMN_WIDTH
            : undefined,
          "data-column-key": key,
          onResize: nextKey
            ? (delta: number, rendered: Record<string, number>) =>
                handleResize(key, nextKey, delta, rendered)
            : undefined,
        }) as AidpResizableTitleProps,
    };
  });

  const renderBody = () => {
    if (query.isLoading) {
      return (
        <div className={styles.stateBlock}>
          <Skeleton active title={false} paragraph={{ rows: 5 }} />
        </div>
      );
    }
    if (query.isError) {
      return (
        <div className={styles.stateBlock}>
          <div className={styles.errorText} role="alert">
            {errorMessage}
          </div>
          <Button onClick={() => void query.refetch()}>
            {t("aidpKnowledge.retry")}
          </Button>
        </div>
      );
    }
    if (rules.length === 0) {
      return (
        <Empty
          className={styles.emptyState}
          description={t("aidpKnowledge.ontologyRulesEmpty")}
        >
          {canManage && (
            <Button type="primary" onClick={openCreate}>
              {t("aidpKnowledge.ontologyRulesCreateAction")}
            </Button>
          )}
        </Empty>
      );
    }
    return (
      <div className={styles.tableArea} ref={tableContainer}>
        <Table<AidpOntologyRule>
          rowKey="rule_id"
          size="middle"
          className={styles.table}
          columns={resizableColumns}
          dataSource={pagedRules}
          pagination={false}
          tableLayout="fixed"
          components={{ header: { cell: AidpResizableTitle } }}
          scroll={{ x: totalWidth }}
          rowSelection={
            canManage
              ? {
                  selectedRowKeys: selectedKeys,
                  onChange: setSelectedKeys,
                }
              : undefined
          }
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_DEFAULT}
                description={t("aidpKnowledge.ontologyRulesSearchEmpty")}
              />
            ),
          }}
        />
      </div>
    );
  };

  return (
    <div className={styles.tab}>
      <div className={styles.toolbar}>
        <Input
          allowClear
          className={styles.searchInput}
          prefix={<SearchOutlined />}
          placeholder={t("aidpKnowledge.ontologyRulesSearchPlaceholder")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
        />
        <div className={styles.toolbarActions}>
          <Button
            type="text"
            aria-label={t("aidpKnowledge.refresh")}
            icon={<ReloadOutlined spin={query.isFetching} />}
            onClick={refresh}
          />
          <Button
            disabled={!canManage || selectedKeys.length === 0}
            onClick={handleBatchDelete}
          >
            {t("aidpKnowledge.ontologyDelete")}
          </Button>
          <Tooltip
            title={
              atLimit ? t("aidpKnowledge.ontologyRulesLimitReached") : undefined
            }
          >
            <Button
              type="primary"
              disabled={!canManage || atLimit}
              onClick={openCreate}
            >
              {t("aidpKnowledge.ontologyRulesCreateAction")}
            </Button>
          </Tooltip>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                {
                  key: "description",
                  label: (
                    <Checkbox
                      checked={visibleColumns.description}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          description: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyRulesDescription")}
                    </Checkbox>
                  ),
                },
                {
                  key: "createTime",
                  label: (
                    <Checkbox
                      checked={visibleColumns.createTime}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          createTime: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyMetadataColumnCreateTime")}
                    </Checkbox>
                  ),
                },
                {
                  key: "updateTime",
                  label: (
                    <Checkbox
                      checked={visibleColumns.updateTime}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          updateTime: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyMetadataColumnUpdateTime")}
                    </Checkbox>
                  ),
                },
              ],
            }}
          >
            <Tooltip title={t("aidpKnowledge.ontologyMetadataColumnSettings")}>
              <Button
                aria-label={t("aidpKnowledge.ontologyMetadataColumnSettings")}
                icon={<SettingOutlined />}
              />
            </Tooltip>
          </Dropdown>
        </div>
      </div>

      {renderBody()}
      {filteredRules.length > 0 && (
        <div className={styles.paginationRow}>
          <AidpPagination
            currentPage={currentPage}
            pageSize={pageSize}
            pageSizeOptions={[10, 20, 50, 100]}
            total={total}
            totalReliable
            hasMore={false}
            selectionHint={
              selectedKeys.length
                ? t("aidpKnowledge.selectedCount", {
                    count: selectedKeys.length,
                  })
                : undefined
            }
            onPageChange={setPage}
            onPageSizeChange={(nextSize) => {
              setPageSize(nextSize);
              setPage(1);
            }}
          />
        </div>
      )}

      <AidpOntologyRuleDrawer
        open={drawerOpen}
        domainId={domainId}
        ruleId={editingRuleId}
        onClose={() => setDrawerOpen(false)}
        onSaved={() => {
          setDrawerOpen(false);
          refresh();
        }}
      />
      <AidpOntologyRuleDetailDrawer
        open={!!detailRule}
        rule={detailRule}
        onClose={() => setDetailRule(null)}
        onEdit={openEdit}
        onDelete={(rule) => {
          setDetailRule(null);
          handleDelete(rule);
        }}
      />
    </div>
  );
};

export default AidpOntologyRulesTab;
