// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Alert, App, Button, Drawer, Empty, Input, Table, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  CloseOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";

import type { AidpDocumentItem } from "@/ext_components/aidp/shared/types/management";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { AIDP_UNKNOWN_VALUE } from "@/ext_components/aidp/shared/utils/aidpKnowledgeDisplay";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { ApiError } from "@/services/api";
import log from "@/lib/logger";
import { useAidpUploadTasks } from "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpUploadTasks";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import AidpResizableTitle from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import {
  AIDP_DETAIL_PAGE_SIZE,
  TASK_COLUMN_MIN_WIDTHS,
  formatDetailDateTime,
  formatFailureTaskDateTime,
  formatFileSize,
  statusCode,
  sumColumnWidths,
  withResizableHeaders,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";

type TaskFilter = 0 | 1 | 2 | 3 | 4 | 5;

interface AidpKnowledgeTasksTabProps {
  knowledgeBaseId: string;
  canEdit: boolean;
  /**
   * Combined page-level pause flag (parent pause prop plus page-level edit
   * modal). Tab-level dialogs mask the tab bar, so they cannot be open while
   * this tab is mounted and need no explicit gating here.
   */
  pollingPaused: boolean;
}

const UNKNOWN = AIDP_UNKNOWN_VALUE;

/**
 * "Upload tasks" tab of the AIDP knowledge base detail view.
 *
 * Shows the AIDP upload-task history, including rows that have not finished
 * processing or have failed, with keyword search, status filtering, failure
 * details and retry actions.
 */
const AidpKnowledgeTasksTab: React.FC<AidpKnowledgeTasksTabProps> = ({
  knowledgeBaseId,
  canEdit,
  pollingPaused,
}) => {
  const { t, i18n } = useTranslation();
  const { message } = App.useApp();
  const [taskKeyword, setTaskKeyword] = useState("");
  const [taskStatus, setTaskStatus] = useState<TaskFilter>(0);
  const [taskParams, setTaskParams] = useState({
    page: 1,
    pageSize: AIDP_DETAIL_PAGE_SIZE,
    keyword: "",
  });
  const { page: taskPage, pageSize: taskPageSize } = taskParams;
  const [failureTask, setFailureTask] = useState<AidpDocumentItem | null>(null);
  const [retryingFileUuid, setRetryingFileUuid] = useState<string | null>(null);
  const [taskColumnWidths, setTaskColumnWidths] = useState<
    Record<string, number>
  >({});

  const tasksQuery = useAidpUploadTasks(
    knowledgeBaseId,
    taskPage,
    taskPageSize,
    taskParams.keyword,
    taskStatus,
    !pollingPaused
  );
  const tasks = tasksQuery.data?.value ?? [];
  const taskTotal = tasksQuery.data?.total_count ?? tasks.length;
  const taskHasMore = tasksQuery.data?.has_more ?? false;
  const taskTotalReliable = tasksQuery.data?.total_reliable !== false;
  const taskStats = tasksQuery.data?.stats ?? {
    total: 0,
    extracting: 0,
    failed: 0,
    success: 0,
    queued: 0,
  };
  const loadingTasks = tasksQuery.isFetching;
  const { refetch: refetchTasks } = tasksQuery;
  const taskError = tasksQuery.isError
    ? getAidpErrorMessage(
        tasksQuery.error,
        t,
        t("aidpKnowledge.detailTasksLoadFailed")
      )
    : undefined;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const keyword = taskKeyword.trim();
      setTaskParams((current) =>
        current.keyword === keyword ? current : { ...current, keyword, page: 1 }
      );
    }, 250);
    return () => window.clearTimeout(timer);
  }, [taskKeyword]);

  const refreshTasks = useCallback(
    () => refetchTasks({ cancelRefetch: false }),
    [refetchTasks]
  );

  const handleRetry = useCallback(
    async (task: AidpDocumentItem) => {
      if (!task.file_uuid) return;
      setRetryingFileUuid(task.file_uuid);
      try {
        const result = await aidpKnowledgeService.retryUploadTasks(
          knowledgeBaseId,
          [task.file_uuid]
        );
        if (result.summary.failed > 0) {
          const first = result.failed_list[0];
          const reason =
            (i18n.language.startsWith("zh")
              ? first?.reason_zh || first?.reason_en
              : first?.reason_en || first?.reason_zh) ||
            first?.message ||
            first?.reason ||
            t("aidpKnowledge.retryTaskFailed");
          const code = first?.error_code ?? first?.code;
          throw code ? new ApiError(code, reason) : new Error(reason);
        }
        message.success(t("aidpKnowledge.retryTaskSuccess"));
        setFailureTask(null);
        void refreshTasks();
      } catch (error) {
        log.error("Failed to retry AIDP upload task:", {
          id: knowledgeBaseId,
          fileUuid: task.file_uuid,
          error,
        });
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.retryTaskFailed"))
        );
      } finally {
        setRetryingFileUuid(null);
      }
    },
    [i18n.language, knowledgeBaseId, message, refreshTasks, t]
  );

  const taskStatusOptions = [
    { value: 0, label: t("aidpKnowledge.taskAll") },
    { value: 1, label: t("aidpKnowledge.taskSuccess") },
    { value: 2, label: t("aidpKnowledge.taskExtracting") },
    { value: 3, label: t("aidpKnowledge.taskVectorFailed") },
    { value: 4, label: t("aidpKnowledge.taskQueued") },
    { value: 5, label: t("aidpKnowledge.taskGraphFailed") },
  ];

  const baseTaskColumns: ColumnsType<AidpDocumentItem> = [
    {
      title: t("aidpKnowledge.detailFileName"),
      dataIndex: "file_name",
      key: "file_name",
      fixed: "left",
      width: 300,
      ellipsis: true,
    },
    {
      title: t("aidpKnowledge.detailFileType"),
      dataIndex: "file_type",
      key: "file_type",
      width: 75,
      render: (value?: string) => value || UNKNOWN,
    },
    {
      title: t("aidpKnowledge.detailFileSize"),
      dataIndex: "file_size",
      key: "file_size",
      width: 80,
      render: (value?: number) => formatFileSize(value),
    },
    {
      title: t("aidpKnowledge.detailUpdateTime"),
      dataIndex: "updated_at",
      key: "updated_at",
      width: 135,
      ellipsis: true,
      render: (value?: string) => formatDetailDateTime(value),
    },
    {
      title: t("aidpKnowledge.detailTaskStatus"),
      dataIndex: "status",
      key: "status",
      width: 120,
      filters: taskStatusOptions.map(({ value, label }) => ({
        text: label,
        value,
      })),
      filterMultiple: false,
      filteredValue: [taskStatus],
      render: (status: AidpDocumentItem["status"]) => {
        const code = statusCode(status);
        const labelKeys: Record<number, string> = {
          1: "aidpKnowledge.taskSuccess",
          2: "aidpKnowledge.taskExtracting",
          3: "aidpKnowledge.taskVectorFailed",
          4: "aidpKnowledge.taskQueued",
          5: "aidpKnowledge.taskGraphFailed",
        };
        const dotColor =
          code === 1
            ? "bg-green-500"
            : code === 3 || code === 5
              ? "bg-red-500"
              : code === 4
                ? "bg-gray-400"
                : "bg-blue-500";
        return (
          <span className="inline-flex items-center gap-2 whitespace-nowrap text-gray-700">
            <i className={`h-2 w-2 shrink-0 rounded-full ${dotColor}`} />
            {code && labelKeys[code] ? t(labelKeys[code]) : (status ?? UNKNOWN)}
          </span>
        );
      },
    },
    {
      title: t("aidpKnowledge.detailOperation"),
      key: "actions",
      fixed: "right",
      width: 175,
      render: (_value, record) => {
        const code = statusCode(record.status);
        if (code !== 3 && code !== 5) return null;
        return (
          <div className="flex items-center gap-3 whitespace-nowrap">
            {canEdit && (
              <Button
                type="link"
                size="small"
                className="px-0"
                loading={retryingFileUuid === record.file_uuid}
                onClick={() => void handleRetry(record)}
              >
                {t("aidpKnowledge.retryTask")}
              </Button>
            )}
            <Button
              type="link"
              size="small"
              className="px-0"
              onClick={() => setFailureTask(record)}
            >
              {t("aidpKnowledge.failureDetails")}
            </Button>
          </div>
        );
      },
    },
  ];
  const taskColumns = withResizableHeaders(
    baseTaskColumns,
    taskColumnWidths,
    TASK_COLUMN_MIN_WIDTHS,
    setTaskColumnWidths
  );

  const descriptionValue = (value: unknown): string => {
    if (value === undefined || value === null || value === "") return UNKNOWN;
    if (typeof value === "boolean")
      return value ? t("common.yes") : t("common.no");
    return String(value);
  };

  return (
    <>
      <section className="flex min-h-[360px] flex-1 shrink-0 flex-col bg-white">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
            <Input
              allowClear
              prefix={<SearchOutlined className="text-gray-400" />}
              value={taskKeyword}
              onChange={(event) => setTaskKeyword(event.target.value)}
              placeholder={t("aidpKnowledge.detailFileSearch")}
              style={{ width: 220, maxWidth: "100%" }}
            />
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-600">
              <Tooltip title={t("aidpKnowledge.taskRetention", { days: 30 })}>
                <span className="inline-flex shrink-0 cursor-help items-center gap-1 text-gray-500">
                  {t("aidpKnowledge.taskStatusSummary", { days: 30 })}
                  <InfoCircleOutlined />
                </span>
              </Tooltip>
              <span className="whitespace-nowrap">
                {t("aidpKnowledge.taskStatTotal", {
                  count: taskStats.total,
                })}
              </span>
              <span className="whitespace-nowrap">
                <i className="mr-1 inline-block h-2 w-2 rounded-full bg-blue-500" />
                {t("aidpKnowledge.taskStatExtracting", {
                  count: taskStats.extracting,
                })}
              </span>
              <span className="whitespace-nowrap">
                <i className="mr-1 inline-block h-2 w-2 rounded-full bg-red-500" />
                {t("aidpKnowledge.taskStatFailed", {
                  count: taskStats.failed,
                })}
              </span>
              <span className="whitespace-nowrap">
                <i className="mr-1 inline-block h-2 w-2 rounded-full bg-green-500" />
                {t("aidpKnowledge.taskStatSuccess", {
                  count: taskStats.success,
                })}
              </span>
            </div>
          </div>
          <Tooltip title={t("aidpKnowledge.refresh")}>
            <Button
              className="ml-auto shrink-0"
              aria-label={t("aidpKnowledge.refresh")}
              icon={<ReloadOutlined spin={loadingTasks} />}
              onClick={() => void refreshTasks()}
            />
          </Tooltip>
        </div>
        {taskError && (
          <Alert type="error" showIcon title={taskError} className="mb-4" />
        )}
        <div className="flex-1">
          <Table<AidpDocumentItem>
            rowKey={(record) => record.file_uuid || record.file_ino_no}
            columns={taskColumns}
            dataSource={tasks}
            loading={loadingTasks}
            onChange={(_pagination, filters) => {
              const selectedStatus = filters.status?.[0];
              const nextStatus =
                typeof selectedStatus === "number" &&
                selectedStatus >= 1 &&
                selectedStatus <= 5
                  ? (selectedStatus as TaskFilter)
                  : 0;
              setTaskStatus(nextStatus);
              setTaskParams((current) => ({ ...current, page: 1 }));
            }}
            pagination={false}
            components={{
              header: { cell: AidpResizableTitle },
            }}
            scroll={{ x: sumColumnWidths(taskColumns) }}
            locale={{
              emptyText: taskError ? null : (
                <Empty description={t("aidpKnowledge.detailTasksEmpty")} />
              ),
            }}
            size="middle"
          />
        </div>
        <div className="mt-4 shrink-0 border-t border-gray-200 py-3">
          <AidpPagination
            currentPage={taskPage}
            pageSize={taskPageSize}
            total={taskTotal}
            totalReliable={taskTotalReliable}
            hasMore={taskHasMore}
            onPageChange={(page) =>
              setTaskParams((current) => ({ ...current, page }))
            }
            onPageSizeChange={(pageSize) =>
              setTaskParams((current) => ({ ...current, pageSize, page: 1 }))
            }
          />
        </div>
      </section>

      <Drawer
        title={
          <div className="flex w-full items-center justify-between">
            <span className="text-xl font-medium leading-7">
              {t("aidpKnowledge.failureDetails")}
            </span>
            <Button
              type="text"
              size="small"
              aria-label={t("common.close")}
              icon={<CloseOutlined />}
              onClick={() => setFailureTask(null)}
            />
          </div>
        }
        closable={false}
        open={Boolean(failureTask)}
        onClose={() => setFailureTask(null)}
        size={640}
      >
        {failureTask && (
          <div className="space-y-4">
            <div className="space-y-1">
              <div className="text-xs font-normal leading-5 text-gray-500">
                {t("aidpKnowledge.detailFailureFileName")}
              </div>
              <div className="break-words text-sm leading-5 text-gray-900">
                {failureTask.file_name || UNKNOWN}
              </div>
            </div>
            <div className="space-y-1">
              <div className="text-xs font-normal leading-5 text-gray-500">
                {t("aidpKnowledge.detailTaskStatus")}
              </div>
              <div className="text-sm leading-5 text-gray-900">
                <span className="inline-flex items-center gap-2 whitespace-nowrap">
                  <i className="h-2 w-2 shrink-0 rounded-full bg-red-500" />
                  {statusCode(failureTask.status) === 5
                    ? t("aidpKnowledge.taskGraphFailed")
                    : t("aidpKnowledge.taskVectorFailed")}
                </span>
              </div>
            </div>
            <div className="space-y-1">
              <div className="text-xs font-normal leading-5 text-gray-500">
                {t("aidpKnowledge.detailTaskUpdatedAt")}
              </div>
              <div className="text-sm leading-5 text-gray-900">
                {formatFailureTaskDateTime(failureTask.updated_at)}
              </div>
            </div>
            <div className="space-y-1">
              <div className="text-xs font-normal leading-5 text-gray-500">
                {t("aidpKnowledge.detailErrorCode")}
              </div>
              <div className="text-sm leading-5 text-gray-900">
                {descriptionValue(failureTask.error_code)}
              </div>
            </div>
            <div className="space-y-1">
              <div className="text-xs font-normal leading-5 text-gray-500">
                {t("aidpKnowledge.detailFailureReason")}
              </div>
              <div className="whitespace-pre-wrap break-words text-sm leading-5 text-gray-900">
                {descriptionValue(
                  failureTask.extraction_failure_reason || failureTask.reason
                )}
              </div>
            </div>
          </div>
        )}
        {failureTask && canEdit && (
          <Button
            className="mt-5"
            type="primary"
            loading={retryingFileUuid === failureTask.file_uuid}
            onClick={() => void handleRetry(failureTask)}
          >
            {t("aidpKnowledge.retryTask")}
          </Button>
        )}
      </Drawer>
    </>
  );
};

export default AidpKnowledgeTasksTab;
