// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Popover, Table, type TableColumnsType } from "antd";
import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";

import { useAidpOntologyDemoMode } from "@/ext_components/aidp/shared/hooks/useAidpOntologyDemoMode";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type { AidpOntologyTask } from "@/ext_components/aidp/shared/types/ontology";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import { formatAidpDateTime } from "@/ext_components/aidp/shared/utils/aidpTime";
import AidpResizableTitle, {
  type AidpResizableTitleProps,
} from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import { AIDP_MIN_COLUMN_WIDTH } from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";
import { useAidpOntologyColumnWidths } from "@/ext_components/aidp/shared/hooks/useAidpOntologyColumnWidths";
import tableStyles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import styles from "./AidpOntologyTasksTab.module.css";

type TaskStatus =
  | "queued"
  | "running"
  | "success"
  | "failed"
  | "partial_success"
  | "terminated";

interface DemoTaskRow {
  id: string;
  name: string;
  status: TaskStatus;
  progress: number | null;
  startTime: string;
  endTime: string | null;
  errorCode?: string;
  errorReason?: string;
}

const TASK_STATUS_MAP: Record<string, TaskStatus> = {
  pending: "queued",
  queued: "queued",
  running: "running",
  processing: "running",
  completed: "success",
  success: "success",
  succeeded: "success",
  failed: "failed",
  partial_success: "partial_success",
  error: "failed",
  terminated: "terminated",
  canceled: "terminated",
  cancelled: "terminated",
};

/** Map one confirmed AIDP task row into the table row shape. */
const toTaskRow = (task: AidpOntologyTask): DemoTaskRow => ({
  id: task.task_id ?? "—",
  name: task.task_type ?? "—",
  status: TASK_STATUS_MAP[String(task.status ?? "").toLowerCase()] ?? "queued",
  progress: task.progress,
  startTime: formatAidpDateTime(task.start_time),
  endTime: task.end_time ? formatAidpDateTime(task.end_time) : null,
  errorReason: task.error_message || undefined,
});

/**
 * Local mock task fixtures.
 *
 * AIDP does expose GET /KnowledgeBase/Tenants/{tenant}/Tasks (task_list
 * envelope), so real mode uses that API. These rows are only for the local mock
 * data source. AIDP tasks carry no ontology domain id, so the real list is
 * tenant-wide rather than scoped to this ontology.
 */
const DEMO_TASKS: DemoTaskRow[] = [
  {
    id: "29303-3",
    name: "同步实体",
    status: "queued",
    progress: 0,
    startTime: "2023-01-12 15:30",
    endTime: null,
  },
  {
    id: "29303-4",
    name: "新增元数据",
    status: "success",
    progress: 100,
    startTime: "2023-01-12 15:30",
    endTime: "2023-01-12 15:31",
  },
  {
    id: "29303-5",
    name: "更新元数据",
    status: "running",
    progress: 45,
    startTime: "2023-01-12 15:30",
    endTime: null,
  },
  {
    id: "29303-6",
    name: "新增元数据",
    status: "failed",
    progress: 50,
    startTime: "2023-01-12 15:30",
    endTime: "2023-01-12 15:31",
    errorCode: "VEC101",
    errorReason:
      "额度耗尽：请求 VEC102 向量服务网络不通、连接超时、服务宕机；VEC103 Chunk 文本过长，超出模型输入 Token 上限；VEC104 批量分片数量超限，接口批量写入被限流。",
  },
  {
    id: "29303-7",
    name: "新增元数据",
    status: "terminated",
    progress: 50,
    startTime: "2023-01-12 15:30",
    endTime: "2023-01-12 15:31",
  },
];

const localizedTaskType = (t: (key: string) => string, raw: string): string => {
  const key = `aidpKnowledge.ontologyTaskType.${raw}`;
  const label = t(key);
  return label === key ? t("aidpKnowledge.ontologyTaskType.unknown") : label;
};

const STATUS_COLOR: Record<TaskStatus, string> = {
  queued: "#8c8c8c",
  running: "#0067d1",
  success: "#15a46e",
  failed: "#e02128",
  partial_success: "#d97706",
  terminated: "#e02128",
};

const AidpOntologyTasksTab: React.FC = () => {
  const { t } = useTranslation();
  const demo = useAidpOntologyDemoMode();
  const scope = useAidpQueryScope();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const tasksQuery = useQuery({
    queryKey: [...scope.key, "ontology-tasks", page, pageSize],
    queryFn: () => aidpOntologyService.listTasks(page, pageSize),
    enabled: scope.enabled && !demo,
    retry: false,
  });

  const rows = useMemo(() => {
    if (demo) return DEMO_TASKS;
    return (tasksQuery.data?.value ?? []).map(toTaskRow);
  }, [demo, tasksQuery.data?.value]);
  const statusLabel = (status: TaskStatus) =>
    t(`aidpKnowledge.ontologyTaskStatus.${status}`);

  const taskNameLabel = (raw: string) => localizedTaskType(t, raw);

  const filteredRows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter(
      (task) =>
        task.name.toLowerCase().includes(needle) ||
        localizedTaskType(t, task.name).toLowerCase().includes(needle) ||
        task.id.toLowerCase().includes(needle)
    );
  }, [rows, search, t]);

  const columns: TableColumnsType<DemoTaskRow> = [
    {
      title: t("aidpKnowledge.ontologyTaskColumnName"),
      dataIndex: "name",
      key: "name",
      width: 140,
      render: (value: string) => (demo ? value : taskNameLabel(value)),
    },
    {
      title: t("aidpKnowledge.ontologyTaskColumnId"),
      dataIndex: "id",
      key: "id",
      width: 120,
    },
    {
      title: t("aidpKnowledge.ontologyTaskColumnStatus"),
      dataIndex: "status",
      key: "status",
      width: 220,
      render: (_value, record) => (
        <div className={styles.statusCell}>
          <div className={styles.statusLine}>
            <span
              className={styles.statusDot}
              style={{ background: STATUS_COLOR[record.status] }}
              aria-hidden="true"
            />
            <span className={styles.statusLabel}>
              {statusLabel(record.status)}
            </span>
            <span className={styles.progressTrack}>
              <span
                className={styles.progressBar}
                style={{
                  width: `${record.progress ?? 0}%`,
                  background: STATUS_COLOR[record.status],
                }}
              />
            </span>
            <span className={styles.progressValue}>
              {record.progress ?? 0}%
            </span>
          </div>
        </div>
      ),
    },
    {
      title: t("aidpKnowledge.ontologyTaskColumnStart"),
      dataIndex: "startTime",
      key: "startTime",
      width: 170,
    },
    {
      title: t("aidpKnowledge.ontologyTaskColumnEnd"),
      dataIndex: "endTime",
      key: "endTime",
      width: 170,
      render: (value: string | null) => value || "—",
    },
    {
      title: t("aidpKnowledge.ontologyColumnActions"),
      key: "actions",
      width: 100,
      fixed: "right",
      render: (_value, record) =>
        record.status === "failed" ? (
          <Popover
            trigger="click"
            placement="bottomRight"
            overlayStyle={{ maxWidth: 420 }}
            title={t("aidpKnowledge.ontologyTaskFailureTitle")}
            content={
              <div className={styles.failureDetail}>
                {record.errorCode && (
                  <div>
                    <span className={styles.failureLabel}>
                      {t("aidpKnowledge.ontologyTaskErrorCode")}
                    </span>
                    <span>{record.errorCode}</span>
                  </div>
                )}
                <div>
                  <span className={styles.failureLabel}>
                    {t("aidpKnowledge.ontologyTaskErrorReason")}
                  </span>
                  <span>{record.errorReason || "—"}</span>
                </div>
              </div>
            }
          >
            <Button type="link" size="small">
              {t("aidpKnowledge.ontologyTaskFailureDetail")}
            </Button>
          </Popover>
        ) : (
          <span className={styles.muted}>—</span>
        ),
    },
  ];

  const columnKeys = columns.map((column) => String(column.key));
  const { tableContainer, columnWidths, totalWidth, handleResize } =
    useAidpOntologyColumnWidths(columnKeys, {
      name: 1.3,
      id: 1,
      status: 2.0,
      startTime: 1.3,
      endTime: 1.3,
      actions: 0.8,
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

  return (
    <div className={tableStyles.tab}>
      <div className={tableStyles.toolbar}>
        <Input
          allowClear
          className={tableStyles.searchInput}
          prefix={<SearchOutlined />}
          placeholder={t("aidpKnowledge.ontologyTaskSearchPlaceholder")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className={tableStyles.toolbarActions}>
          <Button
            type="text"
            aria-label={t("aidpKnowledge.refresh")}
            icon={<ReloadOutlined spin={!demo && tasksQuery.isFetching} />}
            onClick={() => void tasksQuery.refetch()}
          />
        </div>
      </div>
      {!demo && (
        <AidpOntologyGapNote>
          {t("aidpKnowledge.ontologyTaskSortGap")}
        </AidpOntologyGapNote>
      )}
      <div className={tableStyles.tableArea} ref={tableContainer}>
        <Table<DemoTaskRow>
          rowKey="id"
          size="middle"
          className={tableStyles.table}
          columns={resizableColumns}
          dataSource={filteredRows}
          loading={!demo && tasksQuery.isLoading}
          pagination={false}
          tableLayout="fixed"
          components={{ header: { cell: AidpResizableTitle } }}
          scroll={{ x: totalWidth }}
          locale={{
            emptyText: search
              ? t("aidpKnowledge.ontologyTaskSearchEmpty")
              : t("aidpKnowledge.ontologyTaskEmpty"),
          }}
        />
      </div>
      {rows.length > 0 && (
        <AidpPagination
          currentPage={demo ? 1 : page}
          pageSize={demo ? 10 : pageSize}
          pageSizeOptions={[10, 20, 50, 100]}
          total={
            demo ? rows.length : (tasksQuery.data?.total_count ?? rows.length)
          }
          totalReliable
          hasMore={demo ? false : Boolean(tasksQuery.data?.has_more)}
          onPageChange={(nextPage) => setPage(nextPage)}
          onPageSizeChange={(nextSize) => {
            setPageSize(nextSize);
            setPage(1);
          }}
        />
      )}
    </div>
  );
};

export default AidpOntologyTasksTab;
