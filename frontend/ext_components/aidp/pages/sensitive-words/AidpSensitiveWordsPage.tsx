// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  App,
  Button,
  ConfigProvider,
  Input,
  Modal,
  Popover,
  Switch,
  Table,
  Tag,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  EditOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";

import log from "@/lib/logger";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { aidpKnowledgeVisualTheme } from "@/ext_components/aidp/shared/styles/aidpKnowledgeVisualTheme";
import type {
  AidpSensitiveWordItem,
  AidpSensitiveWordMode,
} from "@/ext_components/aidp/shared/types/sensitiveWord";
import AidpResizableTitle from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import { useAidpKnowledgeDetail } from "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpKnowledgeDetail";
import AidpSensitiveWordDrawer from "@/ext_components/aidp/pages/sensitive-words/AidpSensitiveWordDrawer";
import {
  useAidpSensitiveWordList,
  useDeleteAidpSensitiveWords,
} from "@/ext_components/aidp/pages/sensitive-words/hooks/useAidpSensitiveWords";
import {
  SENSITIVE_WORD_COLUMN_WIDTHS,
  sumSensitiveWordColumnWidths,
  withResizableSensitiveWordColumns,
} from "@/ext_components/aidp/pages/sensitive-words/utils/aidpSensitiveWordColumns";
import styles from "./AidpSensitiveWords.module.css";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 300;

const MODE_COLORS: Record<AidpSensitiveWordMode, string> = {
  BLACK: "red",
  WHITE: "green",
};

/**
 * Sensitive words of one AIDP knowledge base.
 *
 * The page is mounted inside the knowledge base detail view. All requests and
 * caches are scoped by `knowledgeBaseId`; the parent remounts the page when the
 * knowledge base changes.
 */
interface AidpSensitiveWordsPageProps {
  knowledgeBaseId: string;
  canManage: boolean;
}

const AidpSensitiveWordsPage: React.FC<AidpSensitiveWordsPageProps> = ({
  knowledgeBaseId,
  canManage,
}) => {
  const { t, i18n } = useTranslation();
  const { message, modal } = App.useApp();

  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [mode, setMode] = useState<AidpSensitiveWordMode | undefined>();
  const [params, setParams] = useState({
    page: 1,
    pageSize: DEFAULT_PAGE_SIZE,
  });
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({
    ...SENSITIVE_WORD_COLUMN_WIDTHS,
  });
  const [drawer, setDrawer] = useState<{
    open: boolean;
    editing: AidpSensitiveWordItem | null;
  }>({ open: false, editing: null });
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [guardrailOpen, setGuardrailOpen] = useState(false);
  const [guardrailEnabled, setGuardrailEnabled] = useState(false);
  const [savingGuardrail, setSavingGuardrail] = useState(false);

  const listQuery = useAidpSensitiveWordList(
    knowledgeBaseId,
    params.page,
    params.pageSize,
    keyword,
    mode
  );
  const detailQuery = useAidpKnowledgeDetail(knowledgeBaseId);
  const deleteMutation = useDeleteAidpSensitiveWords(knowledgeBaseId);
  const rows = useMemo(() => listQuery.data?.value ?? [], [listQuery.data]);
  const total = listQuery.data?.total_count ?? rows.length;
  const hasMore = params.page * params.pageSize < total;
  // Only rows that are still on this page and not built-in can be deleted.
  const selectedRows = useMemo(
    () =>
      rows.filter(
        (row) => selectedKeys.includes(row.id) && row.source !== "BUILT_IN"
      ),
    [rows, selectedKeys]
  );
  const selectedIds = useMemo(
    () => selectedRows.map((row) => row.id),
    [selectedRows]
  );
  const loadErrorMessage = listQuery.isError
    ? listQuery.error instanceof Error && listQuery.error.message
      ? listQuery.error.message
      : t("aidpSensitiveWords.loadFailed")
    : undefined;
  const { refetch } = listQuery;

  // Keep the page inside range after a deletion shrinks the result set.
  useEffect(() => {
    if (!listQuery.isSuccess || listQuery.isFetching) return;
    const lastPage = Math.max(1, Math.ceil(total / params.pageSize));
    if (params.page <= lastPage) return;
    const frame = window.requestAnimationFrame(() =>
      setParams((current) => ({ ...current, page: lastPage }))
    );
    return () => window.cancelAnimationFrame(frame);
  }, [
    listQuery.isSuccess,
    listQuery.isFetching,
    params.page,
    params.pageSize,
    total,
  ]);

  // Debounced search keeps the list in sync without a separate search button.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setKeyword(keywordInput.trim());
      setParams((current) =>
        current.page === 1 ? current : { ...current, page: 1 }
      );
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [keywordInput]);

  const applySearch = () => {
    setKeyword(keywordInput.trim());
    setParams((current) => ({ ...current, page: 1 }));
  };

  const openCreate = useCallback(
    () => setDrawer({ open: true, editing: null }),
    []
  );
  const openEdit = useCallback(
    (item: AidpSensitiveWordItem) => setDrawer({ open: true, editing: item }),
    []
  );
  const closeDrawer = useCallback(
    () => setDrawer({ open: false, editing: null }),
    []
  );

  const runDelete = async (id: string) => {
    try {
      const result = await deleteMutation.mutateAsync([id]);
      const failure = result.failed[0];
      if (failure) {
        message.error(failure.reason || t("aidpSensitiveWords.deleteFailed"));
      } else {
        setSelectedKeys((current) => current.filter((key) => key !== id));
        message.success(t("aidpSensitiveWords.deleteSuccess"));
      }
      await refetch();
    } catch (error) {
      log.error("Failed to delete AIDP sensitive word:", { id, error });
      message.error(
        error instanceof Error && error.message
          ? error.message
          : t("aidpSensitiveWords.deleteFailed")
      );
    }
  };

  const confirmDelete = (item: AidpSensitiveWordItem) => {
    modal.confirm({
      title: t("aidpSensitiveWords.deleteConfirmTitle"),
      content: t("aidpSensitiveWords.deleteConfirmContent", {
        word: item.word,
      }),
      okText: t("common.delete"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: () => runDelete(item.id),
    });
  };

  const openGuardrailModal = async () => {
    setGuardrailEnabled(detailQuery.data?.sensitive_intercept_enable === 1);
    setGuardrailOpen(true);
    try {
      // Read the latest KB detail so a stale cache cannot flip the switch the
      // wrong way. The shared query key also refreshes the parent detail view.
      const result = await detailQuery.refetch();
      if (result.data) {
        setGuardrailEnabled(result.data.sensitive_intercept_enable === 1);
      }
    } catch {
      // Keep the cached value; save errors are reported separately.
    }
  };

  const handleSaveGuardrail = async () => {
    setSavingGuardrail(true);
    try {
      await aidpKnowledgeService.updateKb(knowledgeBaseId, {
        sensitive_intercept_enable: guardrailEnabled ? 1 : 0,
      });
      message.success(t("aidpSensitiveWords.guardrailSaveSuccess"));
      setGuardrailOpen(false);
      await detailQuery.refetch();
    } catch (error) {
      log.error("Failed to update AIDP sensitive word guardrails:", {
        id: knowledgeBaseId,
        error,
      });
      message.error(
        error instanceof Error && error.message
          ? error.message
          : t("aidpSensitiveWords.guardrailSaveFailed")
      );
    } finally {
      setSavingGuardrail(false);
    }
  };

  const handleBatchDelete = () => {
    const targets = selectedRows;
    if (targets.length === 0) return;
    modal.confirm({
      title: t("aidpSensitiveWords.batchDeleteConfirmTitle"),
      content: t("aidpSensitiveWords.batchDeleteConfirmContent", {
        count: targets.length,
      }),
      okText: t("common.delete"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        try {
          const result = await deleteMutation.mutateAsync(
            targets.map((row) => row.id)
          );
          const failedIds = new Set(result.failed.map((item) => item.id));
          // Keep only the rows that still exist and failed, so the user can
          // retry them without reselecting successful deletions.
          setSelectedKeys((current) =>
            current.filter((key) => failedIds.has(String(key)))
          );
          if (result.succeeded > 0) {
            await refetch();
          }
          if (result.failed.length === 0) {
            message.success(t("aidpSensitiveWords.deleteSuccess"));
            return;
          }
          const failures = result.failed.map((item) => {
            const row = targets.find((target) => target.id === item.id);
            return {
              id: item.id,
              word: row?.word || item.id,
              reason: item.reason || t("aidpSensitiveWords.deleteFailed"),
            };
          });
          modal.error({
            title:
              result.succeeded > 0
                ? t("aidpSensitiveWords.batchDeletePartialTitle")
                : t("aidpSensitiveWords.batchDeleteAllFailedTitle"),
            okText: t("common.confirm"),
            centered: true,
            content: (
              <div>
                <p className="mb-2">
                  {t("aidpSensitiveWords.batchDeleteFailureSummary", {
                    success: result.succeeded,
                    failed: result.failed.length,
                  })}
                </p>
                <ul className={styles.batchFailures}>
                  {failures.map((failure) => (
                    <li key={failure.id}>
                      {failure.word}：{failure.reason}
                    </li>
                  ))}
                </ul>
              </div>
            ),
          });
        } catch (error) {
          log.error("Failed to batch delete AIDP sensitive words:", {
            ids: targets.map((row) => row.id),
            error,
          });
          message.error(
            error instanceof Error && error.message
              ? error.message
              : t("aidpSensitiveWords.deleteFailed")
          );
        }
      },
    });
  };

  const columns: ColumnsType<AidpSensitiveWordItem> = [
    {
      title: t("aidpSensitiveWords.columnIndex"),
      key: "index",
      width: SENSITIVE_WORD_COLUMN_WIDTHS.index,
      render: (_value, _record, index) =>
        (params.page - 1) * params.pageSize + index + 1,
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
              onClick={() => openEdit(record)}
            >
              {t("aidpSensitiveWords.edit")}
            </Button>
            <Button
              type="link"
              size="small"
              className="px-1"
              onClick={() => confirmDelete(record)}
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

  const renderBody = () => {
    if (listQuery.isError && rows.length === 0) {
      return (
        <div className={styles.emptyState}>
          <span>{loadErrorMessage || t("aidpSensitiveWords.loadFailed")}</span>
          <Button size="small" onClick={() => void refetch()}>
            {t("aidpKnowledge.retry")}
          </Button>
        </div>
      );
    }
    return (
      <Table<AidpSensitiveWordItem>
        rowKey="id"
        size="middle"
        loading={listQuery.isFetching}
        columns={resizableColumns}
        dataSource={rows}
        rowSelection={
          canManage
            ? {
                selectedRowKeys: selectedKeys,
                onChange: (keys) => setSelectedKeys(keys),
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
          setMode(
            selected === "BLACK" || selected === "WHITE" ? selected : undefined
          );
          setParams((current) => ({ ...current, page: 1 }));
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
    );
  };

  const helpContent = (
    <div className={styles.helpContent}>
      {t("aidpSensitiveWords.dictionaryIntro")}
    </div>
  );

  return (
    <ConfigProvider
      theme={aidpKnowledgeVisualTheme}
      locale={i18n.language.startsWith("zh") ? zhCN : enUS}
    >
      <div className={styles.page}>
        <div className={styles.guardrailHeader}>
          <div className={styles.guardrailTitleRow}>
            <h2 className={styles.guardrailTitle}>
              {t("aidpSensitiveWords.guardrailTitle")}
            </h2>
            {detailQuery.data && (
              <Tag
                color={
                  detailQuery.data.sensitive_intercept_enable === 1
                    ? "green"
                    : "default"
                }
                className="mr-0"
              >
                {detailQuery.data.sensitive_intercept_enable === 1
                  ? t("common.enabled")
                  : t("common.disabled")}
              </Tag>
            )}
            <Popover
              trigger="click"
              placement="bottomLeft"
              content={helpContent}
            >
              <Button
                type="text"
                size="small"
                aria-label={t("aidpSensitiveWords.guardrailHelp")}
                icon={<QuestionCircleOutlined />}
              />
            </Popover>
            {canManage && (
              <Tooltip title={t("aidpSensitiveWords.guardrailEdit")}>
                <Button
                  type="text"
                  size="small"
                  aria-label={t("aidpSensitiveWords.guardrailEdit")}
                  icon={<EditOutlined />}
                  onClick={() => void openGuardrailModal()}
                />
              </Tooltip>
            )}
          </div>
        </div>

        <div className={styles.toolbar}>
          <Input
            allowClear
            className={styles.searchInput}
            placeholder={t("aidpSensitiveWords.searchPlaceholder")}
            prefix={<SearchOutlined />}
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
            onPressEnter={applySearch}
          />
          <div className={styles.toolbarActions}>
            <Tooltip title={t("aidpKnowledge.refresh")}>
              <Button
                aria-label={t("aidpKnowledge.refresh")}
                icon={<ReloadOutlined spin={listQuery.isFetching} />}
                onClick={() => void refetch()}
              />
            </Tooltip>
            {canManage && (
              <>
                <Button
                  disabled={selectedIds.length === 0}
                  onClick={handleBatchDelete}
                >
                  {t("common.delete")}
                </Button>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={openCreate}
                >
                  {t("aidpSensitiveWords.add")}
                </Button>
              </>
            )}
          </div>
        </div>

        <div className={styles.tableArea}>{renderBody()}</div>

        <div className="mt-4 shrink-0 border-t border-gray-200 py-3">
          <AidpPagination
            currentPage={params.page}
            pageSize={params.pageSize}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
            total={total}
            totalReliable
            hasMore={hasMore}
            onPageChange={(page) =>
              setParams((current) => ({ ...current, page }))
            }
            onPageSizeChange={(pageSize) => setParams({ page: 1, pageSize })}
          />
        </div>

        <Modal
          open={guardrailOpen}
          title={t("aidpSensitiveWords.guardrailEdit")}
          onOk={() => void handleSaveGuardrail()}
          onCancel={() => {
            if (!savingGuardrail) setGuardrailOpen(false);
          }}
          okText={t("common.save")}
          cancelText={t("common.cancel")}
          confirmLoading={savingGuardrail}
          okButtonProps={{ disabled: detailQuery.isFetching }}
          centered
          width={520}
          closable={!savingGuardrail}
          maskClosable={!savingGuardrail}
          keyboard={!savingGuardrail}
        >
          <div className={styles.guardrailModal}>
            <div className={styles.guardrailModalControl}>
              <span className={styles.guardrailModalLabel}>
                {t("aidpKnowledge.sensitiveIntercept")}
              </span>
              <Switch
                checked={guardrailEnabled}
                loading={detailQuery.isFetching}
                onChange={setGuardrailEnabled}
                aria-label={t("aidpKnowledge.sensitiveIntercept")}
              />
            </div>
            <p className={styles.guardrailModalHint}>
              {t("aidpSensitiveWords.guardrailSwitchHint")}
            </p>
          </div>
        </Modal>

        <AidpSensitiveWordDrawer
          knowledgeBaseId={knowledgeBaseId}
          open={drawer.open}
          editing={drawer.editing}
          onClose={closeDrawer}
          onSaved={() => void refetch()}
        />
      </div>
    </ConfigProvider>
  );
};

export default AidpSensitiveWordsPage;
