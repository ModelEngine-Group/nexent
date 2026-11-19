// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Popover, Table, type TableColumnsType } from "antd";
import { SearchOutlined } from "@ant-design/icons";

import { useAidpOntologyDemoMode } from "@/ext_components/aidp/shared/hooks/useAidpOntologyDemoMode";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import tableStyles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import AidpOntologyAsyncTaskModal, {
  type AidpOntologyTaskState,
} from "./AidpOntologyAsyncTaskModal";
import styles from "./AidpOntologyTasksTab.module.css";

type TaskStatus = "queued" | "running" | "success" | "failed" | "terminated";

interface DemoTaskRow {
  id: string;
  name: string;
  description: string;
  status: TaskStatus;
  progress: number | null;
  startTime: string;
  endTime: string | null;
  errorCode?: string;
  errorReason?: string;
}

/**
 * Demo-only task fixtures.
 *
 * AIDP exposes no task query API that Nexent may call, so these rows exist only
 * when the local mock data source is active. Real mode renders the empty state
 * and explains that only the initial acceptance response is available.
 */
const DEMO_TASKS: DemoTaskRow[] = [
  {
    id: "29303-3",
    name: "同步实体",
    description:
      "将实体新增或修改的标签同步至全部知识库，并补齐关联知识库的实体标签。",
    status: "queued",
    progress: 0,
    startTime: "2023-01-12 15:30",
    endTime: null,
  },
  {
    id: "29303-4",
    name: "新增元数据",
    description:
      "将实体新增或修改的标签同步至全部知识库，并补齐关联知识库的实体标签。",
    status: "success",
    progress: 100,
    startTime: "2023-01-12 15:30",
    endTime: "2023-01-12 15:31",
  },
  {
    id: "29303-5",
    name: "更新元数据",
    description:
      "将实体新增或修改的标签同步至全部知识库，并补齐关联知识库的实体标签。",
    status: "running",
    progress: 45,
    startTime: "2023-01-12 15:30",
    endTime: null,
  },
  {
    id: "29303-6",
    name: "新增元数据",
    description:
      "将实体新增或修改的标签同步至全部知识库，并补齐关联知识库的实体标签。",
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
    description:
      "将实体新增或修改的标签同步至全部知识库，并补齐关联知识库的实体标签。",
    status: "terminated",
    progress: 50,
    startTime: "2023-01-12 15:30",
    endTime: "2023-01-12 15:31",
  },
];

const STATUS_COLOR: Record<TaskStatus, string> = {
  queued: "#8c8c8c",
  running: "#0067d1",
  success: "#15a46e",
  failed: "#e02128",
  terminated: "#e02128",
};

const AidpOntologyTasksTab: React.FC = () => {
  const { t } = useTranslation();
  const demo = useAidpOntologyDemoMode();
  const [search, setSearch] = useState("");
  const [activeTask, setActiveTask] = useState<DemoTaskRow | null>(null);

  const rows = useMemo(() => (demo ? DEMO_TASKS : []), [demo]);
  const filteredRows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter(
      (task) =>
        task.name.toLowerCase().includes(needle) ||
        task.id.toLowerCase().includes(needle)
    );
  }, [rows, search]);

  const statusLabel = (status: TaskStatus) =>
    t(`aidpKnowledge.ontologyTaskStatus.${status}`);

  const statusCounts = useMemo(() => {
    const counts: Record<TaskStatus, number> = {
      queued: 0,
      running: 0,
      success: 0,
      failed: 0,
      terminated: 0,
    };
    rows.forEach((task) => {
      counts[task.status] += 1;
    });
    return counts;
  }, [rows]);

  const columns: TableColumnsType<DemoTaskRow> = [
    {
      title: t("aidpKnowledge.ontologyTaskColumnName"),
      dataIndex: "name",
      key: "name",
      width: 140,
      render: (value: string, record) =>
        demo ? (
          <button
            type="button"
            className={styles.nameLink}
            onClick={() => setActiveTask(record)}
          >
            {value}
          </button>
        ) : (
          value
        ),
    },
    {
      title: t("aidpKnowledge.ontologyTaskColumnId"),
      dataIndex: "id",
      key: "id",
      width: 120,
    },
    {
      title: t("aidpKnowledge.ontologyTaskColumnDescription"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
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
            <span>{statusLabel(record.status)}</span>
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
            placement="bottomRight"
            title={t("aidpKnowledge.ontologyTaskFailureTitle")}
            content={
              <div className={styles.failureDetail}>
                <div>
                  <span className={styles.failureLabel}>
                    {t("aidpKnowledge.ontologyTaskErrorCode")}
                  </span>
                  <span>{record.errorCode}</span>
                </div>
                <div>
                  <span className={styles.failureLabel}>
                    {t("aidpKnowledge.ontologyTaskErrorReason")}
                  </span>
                  <span>{record.errorReason}</span>
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

  const modalState: AidpOntologyTaskState =
    activeTask?.status === "success"
      ? "success"
      : activeTask?.status === "failed"
        ? "failed"
        : "running";

  return (
    <div className={tableStyles.tab}>
      <div className={styles.taskHeader}>
        <h2 className={styles.taskTitle}>
          {t("aidpKnowledge.ontologyTaskCenterTitle")}
        </h2>
        <div className={styles.legend}>
          <span>{t("aidpKnowledge.ontologyTaskWeekSummary")}</span>
          <span className={styles.legendItem}>
            {t("aidpKnowledge.ontologyTaskTotal")} {rows.length}
          </span>
          {(["running", "failed", "success", "queued"] as TaskStatus[]).map(
            (status) => (
              <span key={status} className={styles.legendItem}>
                <span
                  className={styles.statusDot}
                  style={{ background: STATUS_COLOR[status] }}
                  aria-hidden="true"
                />
                {statusLabel(status)} {statusCounts[status]}
              </span>
            )
          )}
        </div>
      </div>
      <div className={tableStyles.toolbar}>
        <Input
          allowClear
          className={tableStyles.searchInput}
          prefix={<SearchOutlined />}
          placeholder={t("aidpKnowledge.ontologyTaskSearchPlaceholder")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        {demo && <div className={tableStyles.toolbarActions}> </div>}
      </div>
      <AidpOntologyGapNote>
        {demo
          ? t("aidpKnowledge.ontologyTaskDemoGap")
          : t("aidpKnowledge.ontologyTaskRealGap")}
      </AidpOntologyGapNote>
      <div className={tableStyles.tableArea}>
        <Table<DemoTaskRow>
          rowKey="id"
          size="middle"
          className={tableStyles.table}
          columns={columns}
          dataSource={filteredRows}
          pagination={false}
          tableLayout="fixed"
          scroll={{ x: 1100 }}
          locale={{
            emptyText: search
              ? t("aidpKnowledge.ontologyTaskSearchEmpty")
              : t("aidpKnowledge.ontologyTaskEmpty"),
          }}
        />
      </div>
      {rows.length > 0 && (
        <AidpPagination
          currentPage={1}
          pageSize={10}
          pageSizeOptions={[10]}
          total={rows.length}
          totalReliable
          hasMore={false}
          selectedCount={0}
          onPageChange={() => undefined}
        />
      )}

      {demo && (
        <AidpOntologyAsyncTaskModal
          open={!!activeTask}
          taskName={activeTask?.name ?? ""}
          taskId={activeTask?.id ?? null}
          demo={demo}
          initialState={modalState}
          onClose={() => setActiveTask(null)}
        />
      )}
    </div>
  );
};

export default AidpOntologyTasksTab;
