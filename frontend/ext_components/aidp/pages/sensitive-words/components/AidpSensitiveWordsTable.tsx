// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";

import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import type {
  AidpSensitiveWordItem,
  AidpSensitiveWordMode,
} from "@/ext_components/aidp/shared/types/sensitiveWord";
import AidpResizableTitle from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import {
  SENSITIVE_WORD_COLUMN_WIDTHS,
  sumSensitiveWordColumnWidths,
  withResizableSensitiveWordColumns,
} from "@/ext_components/aidp/pages/sensitive-words/utils/aidpSensitiveWordColumns";
import styles from "../AidpSensitiveWords.module.css";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;

const MODE_COLORS: Record<AidpSensitiveWordMode, string> = {
  BLACK: "red",
  WHITE: "green",
};

interface AidpSensitiveWordsTableProps {
  rows: AidpSensitiveWordItem[];
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
  errorMessage?: string;
  keyword: string;
  mode?: AidpSensitiveWordMode;
  canManage: boolean;
  selectedKeys: React.Key[];
  onSelectionChange: (keys: React.Key[]) => void;
  onModeChange: (mode?: AidpSensitiveWordMode) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  onEdit: (item: AidpSensitiveWordItem) => void;
  onDelete: (item: AidpSensitiveWordItem) => void;
  onRetry: () => void;
}

/** Resizable, server-paginated dictionary table with header filters. */
const AidpSensitiveWordsTable: React.FC<AidpSensitiveWordsTableProps> = ({
  rows,
  total,
  page,
  pageSize,
  loading,
  errorMessage,
  keyword,
  mode,
  canManage,
  selectedKeys,
  onSelectionChange,
  onModeChange,
  onPageChange,
  onPageSizeChange,
  onEdit,
  onDelete,
  onRetry,
}) => {
  const { t } = useTranslation();
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({
    ...SENSITIVE_WORD_COLUMN_WIDTHS,
  });

  const columns: ColumnsType<AidpSensitiveWordItem> = [
    {
      title: t("aidpSensitiveWords.columnIndex"),
      key: "index",
      width: SENSITIVE_WORD_COLUMN_WIDTHS.index,
      render: (_value, _record, index) => (page - 1) * pageSize + index + 1,
    },
    {
      title: t("aidpSensitiveWords.columnWord"),
      dataIndex: "word",
      key: "word",
      ellipsis: { showTitle: false },
      render: (_value, record) => (
        <div className={styles.wordCell}>
          <Tooltip title={record.word}>
            <span className={styles.wordText}>{record.word}</span>
          </Tooltip>
          {record.source === "BUILT_IN" && (
            <Tag color="default" className="mr-0">
              {t("aidpSensitiveWords.builtIn")}
            </Tag>
          )}
        </div>
      ),
    },
    {
      title: t("aidpSensitiveWords.columnMode"),
      dataIndex: "mode",
      key: "mode",
      width: SENSITIVE_WORD_COLUMN_WIDTHS.mode,
      filters: [
        { text: t("aidpSensitiveWords.modeBlack"), value: "BLACK" },
        { text: t("aidpSensitiveWords.modeWhite"), value: "WHITE" },
      ],
      filterMultiple: false,
      filteredValue: mode ? [mode] : null,
      render: (value: AidpSensitiveWordMode) => (
        <Tag color={MODE_COLORS[value] ?? "default"} className="mr-0">
          {value === "WHITE"
            ? t("aidpSensitiveWords.modeWhite")
            : t("aidpSensitiveWords.modeBlack")}
        </Tag>
      ),
    },
    {
      title: t("aidpSensitiveWords.columnDescription"),
      dataIndex: "description",
      key: "description",
      ellipsis: { showTitle: false },
      render: (value: string) => (
        <Tooltip title={value}>
          <span>{value}</span>
        </Tooltip>
      ),
    },
    {
      title: t("aidpSensitiveWords.columnActions"),
      key: "actions",
      width: SENSITIVE_WORD_COLUMN_WIDTHS.actions,
      render: (_value, record) =>
        canManage && record.source !== "BUILT_IN" ? (
          <div className={styles.actions}>
            <Button
              type="link"
              size="small"
              className="px-1"
              onClick={() => onEdit(record)}
            >
              {t("aidpSensitiveWords.edit")}
            </Button>
            <Button
              type="link"
              size="small"
              className="px-1"
              onClick={() => onDelete(record)}
            >
              {t("common.delete")}
            </Button>
          </div>
        ) : null,
    },
  ];

  const resizableColumns = withResizableSensitiveWordColumns(
    columns,
    columnWidths,
    setColumnWidths
  );
  const tableWidth = sumSensitiveWordColumnWidths(resizableColumns);
  const hasMore = page * pageSize < total;
  const pagination = (
    <div className="mt-4 shrink-0 border-t border-gray-200 py-3">
      <AidpPagination
        currentPage={page}
        pageSize={pageSize}
        pageSizeOptions={PAGE_SIZE_OPTIONS}
        total={total}
        totalReliable
        hasMore={hasMore}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />
    </div>
  );

  if (errorMessage && rows.length === 0) {
    return (
      <>
        <div className={styles.tableArea}>
          <div className={styles.emptyState}>
            <span>{errorMessage}</span>
            <Button size="small" onClick={onRetry}>
              {t("aidpKnowledge.retry")}
            </Button>
          </div>
        </div>
        {pagination}
      </>
    );
  }

  return (
    <>
      <div className={styles.tableArea}>
        <Table<AidpSensitiveWordItem>
          rowKey="id"
          size="middle"
          loading={loading}
          columns={resizableColumns}
          dataSource={rows}
          rowSelection={
            canManage
              ? {
                  selectedRowKeys: selectedKeys,
                  onChange: onSelectionChange,
                  getCheckboxProps: (record) => ({
                    disabled: record.source === "BUILT_IN",
                  }),
                }
              : undefined
          }
          pagination={false}
          tableLayout="fixed"
          components={{ header: { cell: AidpResizableTitle } }}
          scroll={{ x: tableWidth }}
          onChange={(_pagination, filters) => {
            const selected = filters.mode?.[0];
            onModeChange(
              selected === "BLACK" || selected === "WHITE"
                ? selected
                : undefined
            );
          }}
          locale={{
            emptyText: (
              <div className={styles.emptyState}>
                {keyword.trim() || mode
                  ? t("aidpSensitiveWords.searchEmpty")
                  : t("aidpSensitiveWords.empty")}
              </div>
            ),
          }}
        />
      </div>

      {pagination}
    </>
  );
};

export default AidpSensitiveWordsTable;
