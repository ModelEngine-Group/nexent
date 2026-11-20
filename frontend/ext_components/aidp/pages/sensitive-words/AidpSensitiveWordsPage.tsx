// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { App, Button, ConfigProvider, Popover, Tag, Tooltip } from "antd";
import { EditOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";

import log from "@/lib/logger";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { aidpKnowledgeVisualTheme } from "@/ext_components/aidp/shared/styles/aidpKnowledgeVisualTheme";
import type {
  AidpSensitiveWordItem,
  AidpSensitiveWordMode,
} from "@/ext_components/aidp/shared/types/sensitiveWord";
import { useAidpKnowledgeDetail } from "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpKnowledgeDetail";
import AidpSensitiveWordDrawer from "@/ext_components/aidp/pages/sensitive-words/AidpSensitiveWordDrawer";
import AidpSensitiveWordsTable from "@/ext_components/aidp/pages/sensitive-words/components/AidpSensitiveWordsTable";
import AidpSensitiveWordsToolbar from "@/ext_components/aidp/pages/sensitive-words/components/AidpSensitiveWordsToolbar";
import AidpGuardrailSettingsModal from "@/ext_components/aidp/pages/sensitive-words/components/AidpGuardrailSettingsModal";
import {
  useAidpSensitiveWordList,
  useDeleteAidpSensitiveWords,
} from "@/ext_components/aidp/pages/sensitive-words/hooks/useAidpSensitiveWords";
import styles from "./AidpSensitiveWords.module.css";

const DEFAULT_PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 300;

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
              trigger="hover"
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

        <AidpSensitiveWordsToolbar
          keywordInput={keywordInput}
          loading={listQuery.isFetching}
          canManage={canManage}
          selectedCount={selectedIds.length}
          onKeywordChange={setKeywordInput}
          onSearch={applySearch}
          onRefresh={() => void refetch()}
          onBatchDelete={handleBatchDelete}
          onCreate={openCreate}
        />

        <AidpSensitiveWordsTable
          rows={rows}
          total={total}
          page={params.page}
          pageSize={params.pageSize}
          loading={listQuery.isFetching}
          errorMessage={loadErrorMessage}
          keyword={keyword}
          mode={mode}
          canManage={canManage}
          selectedKeys={selectedKeys}
          onSelectionChange={setSelectedKeys}
          onModeChange={(nextMode) => {
            setMode(nextMode);
            setParams((current) => ({ ...current, page: 1 }));
          }}
          onPageChange={(page) =>
            setParams((current) => ({ ...current, page }))
          }
          onPageSizeChange={(pageSize) => setParams({ page: 1, pageSize })}
          onEdit={openEdit}
          onDelete={confirmDelete}
          onRetry={() => void refetch()}
        />

        <AidpGuardrailSettingsModal
          open={guardrailOpen}
          enabled={guardrailEnabled}
          loading={detailQuery.isFetching}
          saving={savingGuardrail}
          onToggle={setGuardrailEnabled}
          onSave={handleSaveGuardrail}
          onCancel={() => {
            if (!savingGuardrail) setGuardrailOpen(false);
          }}
        />

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
