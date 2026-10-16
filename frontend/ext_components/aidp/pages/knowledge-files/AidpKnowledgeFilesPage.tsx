// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { UserIdentity } from "@/components/auth/UserIdentity";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  App,
  Alert,
  Breadcrumb,
  Button,
  Empty,
  Input,
  Table,
  Tabs,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  ClockCircleOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SearchOutlined,
  TeamOutlined,
  UserOutlined,
  UploadOutlined,
} from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";
import type {
  AidpDocumentItem,
  AidpKbDetail,
} from "@/ext_components/aidp/shared/types/management";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import {
  AIDP_UNKNOWN_VALUE,
  formatAidpCreator,
  formatAidpDocumentCount,
} from "@/ext_components/aidp/shared/utils/aidpKnowledgeDisplay";
import { useAidpGroupOptions } from "@/ext_components/aidp/shared/hooks/useAidpGroupOptions";
import { useAidpKnowledgeFiles } from "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpKnowledgeFiles";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { ApiError } from "@/services/api";
import log from "@/lib/logger";
import { usePermission } from "@/hooks/permission/usePermission";
import { useAidpKnowledgeDetail } from "./hooks/useAidpKnowledgeDetail";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import AidpImportDrawer from "@/ext_components/aidp/features/file-import/AidpImportDrawer";
import AidpUpdateKbModal from "@/ext_components/aidp/pages/knowledge-files/AidpUpdateKbModal";
import AidpGroupNamesDisplay from "@/ext_components/aidp/shared/components/AidpGroupNamesDisplay";
import AidpResizableTitle from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import { AidpDetailField } from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeDetailInformation";
import AidpKnowledgeTasksTab from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeTasksTab";
import AidpKnowledgeInformationTab from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeInformationTab";
import {
  AIDP_DETAIL_PAGE_SIZE,
  FILE_COLUMN_MIN_WIDTHS,
  fileDeleteStatusCode,
  formatDetailDateTime,
  formatFileSize,
  sumColumnWidths,
  withResizableHeaders,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";

interface AidpKnowledgeFilesPageProps {
  knowledgeBase: AidpKnowledgeBaseItem;
  onBack: () => void;
  onDelete: (knowledgeBase: AidpKnowledgeBaseItem) => void;
  onUpdated: (knowledgeBase: AidpKnowledgeBaseItem) => void;
  pollingPaused?: boolean;
}

type DetailTab = "files" | "tasks" | "information";

// AIDP caps a single batch document removal request at 10 files.
const AIDP_BATCH_DELETE_MAX = 10;
const UNKNOWN = AIDP_UNKNOWN_VALUE;

/** A file whose deletion is already in progress must not be deleted again. */
const isFileDeleting = (status: AidpDocumentItem["file_status"]): boolean =>
  fileDeleteStatusCode(status) === 1;

const AidpKnowledgeFilesPage: React.FC<AidpKnowledgeFilesPageProps> = ({
  knowledgeBase,
  onBack,
  onDelete,
  onUpdated,
  pollingPaused = false,
}) => {
  const { t, i18n } = useTranslation();
  const { message, modal } = App.useApp();
  const {
    groupOptions,
    canReadGroups,
    canConfigureGroupPermissions,
    groupsError,
  } = useAidpGroupOptions();
  const { can } = usePermission();
  const detailQuery = useAidpKnowledgeDetail(knowledgeBase.kds_id);
  const detail = useMemo<AidpKbDetail>(
    () => ({ ...knowledgeBase, ...detailQuery.data }),
    [knowledgeBase, detailQuery.data]
  );
  const [activeTab, setActiveTab] = useState<DetailTab>("files");
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [editingKbMode, setEditingKbMode] = useState<
    "metadata" | "permissions" | null
  >(null);
  const [importOpen, setImportOpen] = useState(false);
  const [fileKeyword, setFileKeyword] = useState("");
  const [fileParams, setFileParams] = useState({
    page: 1,
    pageSize: AIDP_DETAIL_PAGE_SIZE,
    keyword: "",
  });
  const { page: filePage, pageSize: filePageSize } = fileParams;
  const filesQuery = useAidpKnowledgeFiles(
    knowledgeBase.kds_id,
    filePage,
    filePageSize,
    fileParams.keyword,
    pollingPaused || importOpen || deleteConfirmOpen || editingKbMode !== null
  );
  // Memoized so callbacks depending on `files` keep a stable reference when
  // the query has not produced a new page.
  const files = useMemo(() => filesQuery.data?.value ?? [], [filesQuery.data]);
  const fileTotal = filesQuery.data?.total_count ?? files.length;
  const fileHasMore = filesQuery.data?.has_more ?? false;
  const fileTotalReliable = filesQuery.data?.total_reliable !== false;
  const loadingFiles = filesQuery.isFetching;
  const { refetch: refetchFiles } = filesQuery;
  const fileError = filesQuery.isError
    ? getAidpErrorMessage(
        filesQuery.error,
        t,
        t("aidpKnowledge.detailFilesLoadFailed")
      )
    : undefined;

  const [selectedFileKeys, setSelectedFileKeys] = useState<React.Key[]>([]);
  const [fileColumnWidths, setFileColumnWidths] = useState<
    Record<string, number>
  >({});

  const groupNames = useMemo(() => {
    const names = new Map(
      groupOptions.map((option) => [option.value, option.label])
    );
    return (detail.group_ids || []).map((id) => names.get(id) || UNKNOWN);
  }, [detail.group_ids, groupOptions]);
  const canEdit = detail.permission === "EDIT";
  const canDeleteKb = canEdit && can("kb:delete");
  const isAvailable =
    detail.resource_status !== "UNAVAILABLE" &&
    detail.resource_status !== "ORPHANED";

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const keyword = fileKeyword.trim();
      setFileParams((current) =>
        current.keyword === keyword ? current : { ...current, keyword, page: 1 }
      );
    }, 250);
    return () => window.clearTimeout(timer);
  }, [fileKeyword]);

  const refreshFiles = useCallback(
    () => refetchFiles({ cancelRefetch: false }),
    [refetchFiles]
  );

  useEffect(() => {
    if (
      !filesQuery.isSuccess ||
      filesQuery.isFetching ||
      files.length ||
      filePage <= 1
    )
      return;
    const lastPage = fileTotalReliable
      ? Math.max(1, Math.ceil(fileTotal / filePageSize))
      : filePage - 1;
    const frame = window.requestAnimationFrame(() =>
      setFileParams((current) => ({
        ...current,
        page: Math.min(filePage - 1, lastPage),
      }))
    );
    return () => window.cancelAnimationFrame(frame);
  }, [
    filesQuery.isSuccess,
    filesQuery.isFetching,
    files.length,
    filePage,
    filePageSize,
    fileTotal,
    fileTotalReliable,
  ]);

  const handleDownload = useCallback(
    async (file: AidpDocumentItem) => {
      try {
        const response = await aidpKnowledgeService.downloadDoc(
          knowledgeBase.kds_id,
          file.file_uuid
        );
        const blobUrl = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = blobUrl;
        link.download = file.file_name || "download";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(blobUrl);
      } catch (error) {
        log.error("Failed to download AIDP file:", {
          id: knowledgeBase.kds_id,
          fileUuid: file.file_uuid,
          error,
        });
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.downloadFailed"))
        );
      }
    },
    [knowledgeBase.kds_id, message, t]
  );

  const handleDeleteFile = useCallback(
    async (file: AidpDocumentItem) => {
      setDeleteConfirmOpen(true);
      // Await mode keeps failed confirmations open without rethrowing globally.
      await modal.confirm({
        title: t("aidpKnowledge.deleteDocTitle"),
        centered: true,
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        afterClose: () => setDeleteConfirmOpen(false),
        content: file.file_name,
        onOk: async () => {
          try {
            const result = await aidpKnowledgeService.removeDoc(
              knowledgeBase.kds_id,
              file.file_uuid
            );
            const failed = result.failed_list.find(
              (item) => item.file_uuid === file.file_uuid
            );
            if (
              failed ||
              result.summary.failed > 0 ||
              !result.success_list.some(
                (item) => item.file_uuid === file.file_uuid
              )
            ) {
              const reason =
                (i18n.language.startsWith("zh")
                  ? failed?.reason_zh || failed?.reason_en
                  : failed?.reason_en || failed?.reason_zh) ||
                failed?.message ||
                failed?.reason ||
                t("aidpKnowledge.deleteDocFailed");
              const code = failed?.error_code ?? failed?.code;
              throw code ? new ApiError(code, reason) : new Error(reason);
            }
            message.success(t("aidpKnowledge.deleteDocSuccess"));
            void refreshFiles();
          } catch (error) {
            log.error("Failed to delete AIDP file:", {
              id: knowledgeBase.kds_id,
              fileUuid: file.file_uuid,
              error,
            });
            message.error(
              getAidpErrorMessage(error, t, t("aidpKnowledge.deleteDocFailed"))
            );
            throw error;
          }
        },
      });
    },
    [refreshFiles, i18n.language, knowledgeBase.kds_id, message, modal, t]
  );

  const handleBatchDeleteFiles = useCallback(() => {
    // Selection keys can fall back to file_ino_no; map them back to the
    // current page records so only real file UUIDs are sent to AIDP.
    const fileUuids = files
      .filter(
        (file) =>
          selectedFileKeys.includes(file.file_uuid || file.file_ino_no) &&
          // A stale selection can still hold a row that flipped to "deleting"
          // between polls; it must not be removed again.
          !isFileDeleting(file.file_status)
      )
      .map((file) => file.file_uuid)
      .filter(Boolean);
    if (fileUuids.length === 0) return;
    // AIDP rejects oversized batch removals; guard before confirming.
    if (fileUuids.length > AIDP_BATCH_DELETE_MAX) {
      message.warning(
        t("aidpKnowledge.deleteDocsLimit", { max: AIDP_BATCH_DELETE_MAX })
      );
      return;
    }
    setDeleteConfirmOpen(true);
    // modal.confirm returns a thenable without .catch; wrap it so a failed
    // confirmation surfaces through the dialog instead of an unhandled rejection.
    void Promise.resolve(
      modal.confirm({
        title: t("aidpKnowledge.deleteDocsTitle", { count: fileUuids.length }),
        centered: true,
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        okButtonProps: { danger: true },
        afterClose: () => setDeleteConfirmOpen(false),
        onOk: async () => {
          try {
            const result = await aidpKnowledgeService.removeDocs(
              knowledgeBase.kds_id,
              fileUuids
            );
            const { success, failed } = result.summary;
            if (failed === 0) {
              message.success(t("aidpKnowledge.deleteDocSuccess"));
            } else if (success === 0) {
              const first = result.failed_list[0];
              const reason =
                (i18n.language.startsWith("zh")
                  ? first?.reason_zh || first?.reason_en
                  : first?.reason_en || first?.reason_zh) ||
                first?.message ||
                first?.reason ||
                t("aidpKnowledge.deleteDocFailed");
              const code = first?.error_code ?? first?.code;
              throw code ? new ApiError(code, reason) : new Error(reason);
            } else {
              message.warning(
                t("aidpKnowledge.deleteDocsPartial", { success, failed })
              );
            }
            void refreshFiles();
            void detailQuery.refetch();
          } catch (error) {
            log.error("Failed to batch delete AIDP files:", {
              id: knowledgeBase.kds_id,
              count: fileUuids.length,
              error,
            });
            message.error(
              getAidpErrorMessage(error, t, t("aidpKnowledge.deleteDocFailed"))
            );
            throw error;
          }
        },
      })
    ).catch(() => undefined);
  }, [
    detailQuery,
    files,
    i18n.language,
    knowledgeBase.kds_id,
    message,
    modal,
    refreshFiles,
    selectedFileKeys,
    t,
  ]);

  const baseFileColumns: ColumnsType<AidpDocumentItem> = [
    {
      title: t("aidpKnowledge.detailFileName"),
      dataIndex: "file_name",
      key: "file_name",
      fixed: "left",
      width: 220,
      ellipsis: true,
      render: (value: string) => (
        <span className="text-blue-600">{value || UNKNOWN}</span>
      ),
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
      width: 85,
      render: (value?: number) => formatFileSize(value),
    },
    {
      title: t("aidpKnowledge.detailImportMode"),
      key: "import_mode",
      width: 120,
      ellipsis: true,
      render: () => t("aidpKnowledge.detailLocalImport"),
    },
    {
      title: t("aidpKnowledge.detailFirstUploadTime"),
      dataIndex: "created_at",
      key: "created_at",
      width: 150,
      ellipsis: true,
      render: (value?: string) => formatDetailDateTime(value),
    },
    {
      title: t("aidpKnowledge.detailUpdateTime"),
      dataIndex: "updated_at",
      key: "updated_at",
      width: 150,
      ellipsis: true,
      render: (value?: string) => formatDetailDateTime(value),
    },
    {
      title: t("aidpKnowledge.detailFileDeleteStatus"),
      dataIndex: "file_status",
      key: "file_status",
      width: 100,
      render: (value: AidpDocumentItem["file_status"]) => {
        const code = fileDeleteStatusCode(value);
        const labelKey =
          code === 1
            ? "aidpKnowledge.fileDeleteStatusDeleting"
            : code === 2
              ? "aidpKnowledge.fileDeleteStatusFailed"
              : "aidpKnowledge.fileDeleteStatusIngested";
        const dotColor =
          code === 2
            ? "bg-red-500"
            : code === 1
              ? "bg-blue-500"
              : "bg-green-500";
        return (
          <span className="inline-flex items-center gap-2 whitespace-nowrap text-gray-700">
            <i className={`h-2 w-2 shrink-0 rounded-full ${dotColor}`} />
            {t(labelKey)}
          </span>
        );
      },
    },
    {
      title: t("aidpKnowledge.detailOperation"),
      key: "actions",
      fixed: "right",
      width: 120,
      render: (_value, record) => (
        <div className="flex items-center gap-3 whitespace-nowrap">
          <Button
            type="link"
            size="small"
            className="px-0"
            onClick={() => void handleDownload(record)}
          >
            {t("aidpKnowledge.download")}
          </Button>
          {canEdit && (
            <Button
              type="link"
              size="small"
              className="px-0"
              disabled={isFileDeleting(record.file_status)}
              onClick={() => handleDeleteFile(record)}
            >
              {t("common.delete")}
            </Button>
          )}
        </div>
      ),
    },
  ];
  const fileColumns = withResizableHeaders(
    baseFileColumns,
    fileColumnWidths,
    FILE_COLUMN_MIN_WIDTHS,
    setFileColumnWidths
  );

  const privateScope = detail.ingroup_permission === "PRIVATE";

  return (
    <div className="flex h-full min-h-0 w-full flex-col gap-3 overflow-y-auto pb-4">
      <Breadcrumb
        className="shrink-0"
        items={[
          {
            title: (
              <button
                type="button"
                onClick={onBack}
                className="!text-lg !leading-7 text-gray-500 hover:text-blue-600"
              >
                {t("aidpKnowledge.breadcrumbKnowledgeBase")}
              </button>
            ),
          },
          {
            title: (
              <span className="!text-lg !font-semibold !leading-7 text-gray-800">
                {t("aidpKnowledge.detailBreadcrumb")}
              </span>
            ),
          },
        ]}
      />

      <section className="@container shrink-0 rounded-xl border border-violet-100 bg-gradient-to-r from-violet-50 via-white to-blue-50 px-6 py-3">
        <div className="flex items-start gap-4">
          <span className="flex h-24 w-24 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-6xl text-violet-600">
            <DatabaseOutlined />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-2">
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <Tooltip title={detail.kds_name}>
                    <h1 className="truncate text-lg font-semibold text-gray-800">
                      {detail.kds_name}
                    </h1>
                  </Tooltip>
                  {canEdit && (
                    <Tooltip
                      title={t("aidpKnowledge.detailEditNameDescription")}
                    >
                      <Button
                        type="text"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() => setEditingKbMode("metadata")}
                      />
                    </Tooltip>
                  )}
                </div>
                <Tooltip
                  title={detail.description}
                  styles={{ root: { maxWidth: 480 } }}
                >
                  <p className="mt-1 truncate text-sm leading-6 text-gray-600">
                    {detail.description || t("aidpKnowledge.noDescription")}
                  </p>
                </Tooltip>
              </div>
              {canDeleteKb && (
                <Button
                  icon={<DeleteOutlined />}
                  onClick={() => onDelete(detail)}
                >
                  {t("common.delete")}
                </Button>
              )}
            </div>
            <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 @min-[600px]:grid-cols-2 @min-[900px]:grid-cols-3 @min-[1200px]:grid-cols-5">
              <div className="flex min-w-0 items-center gap-3">
                <FileTextOutlined className="rounded-lg bg-violet-100 p-2 text-lg text-violet-600" />
                <AidpDetailField label={t("aidpKnowledge.detailTabFiles")}>
                  {formatAidpDocumentCount(
                    !fileParams.keyword && filesQuery.isSuccess
                      ? fileTotal
                      : detail.document_count
                  )}
                </AidpDetailField>
              </div>
              <div className="flex min-w-0 items-center gap-3">
                <DatabaseOutlined className="rounded-lg bg-violet-100 p-2 text-lg text-violet-600" />
                <AidpDetailField label={t("aidpKnowledge.detailPermissions")}>
                  {privateScope
                    ? t("aidpKnowledge.scopePrivate")
                    : t("aidpKnowledge.scopeShared")}
                </AidpDetailField>
              </div>
              <div className="flex min-w-0 items-center gap-3">
                <TeamOutlined className="rounded-lg bg-violet-100 p-2 text-lg text-violet-600" />
                <AidpDetailField label={t("aidpKnowledge.detailAllowedGroups")}>
                  {privateScope ? (
                    t("aidpKnowledge.detailOwnerOnly")
                  ) : canReadGroups && !groupsError && groupNames.length > 0 ? (
                    <AidpGroupNamesDisplay groupNames={groupNames} />
                  ) : (
                    UNKNOWN
                  )}
                </AidpDetailField>
              </div>
              <div className="flex min-w-0 items-center gap-3">
                <ClockCircleOutlined className="rounded-lg bg-violet-100 p-2 text-lg text-violet-600" />
                <AidpDetailField label={t("aidpKnowledge.detailCreatedAt")}>
                  {formatDetailDateTime(detail.created_at)}
                </AidpDetailField>
              </div>
              <div className="flex min-w-0 items-center gap-3">
                <UserOutlined className="rounded-lg bg-violet-100 p-2 text-lg text-violet-600" />
                <AidpDetailField label={t("aidpKnowledge.detailCreator")}>
                  <UserIdentity
                    casUsername={detail.creator_cas_username}
                    fallback={formatAidpCreator(detail.creator_name)}
                  />
                </AidpDetailField>
              </div>
            </dl>
          </div>
        </div>
      </section>

      {detailQuery.isError && (
        <Alert
          type="error"
          showIcon
          title={getAidpErrorMessage(
            detailQuery.error,
            t,
            t("aidpKnowledge.detailLoadFailed")
          )}
        />
      )}
      {groupsError && (
        <Alert
          type="error"
          showIcon
          title={getAidpErrorMessage(
            groupsError,
            t,
            t("aidpKnowledge.groupsLoadFailed")
          )}
        />
      )}
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as DetailTab)}
        className="shrink-0 [&>.ant-tabs-nav]:mb-0 [&>.ant-tabs-content-holder]:hidden"
        tabBarStyle={{ marginBottom: 0 }}
        items={[
          { key: "files", label: t("aidpKnowledge.detailTabUploadedFiles") },
          { key: "tasks", label: t("aidpKnowledge.detailTabTasks") },
          {
            key: "information",
            label: t("aidpKnowledge.detailTabInformation"),
          },
        ]}
      />

      {activeTab === "files" && (
        <section className="flex min-h-[360px] flex-1 shrink-0 flex-col bg-white">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <Input
              allowClear
              prefix={<SearchOutlined className="text-gray-400" />}
              value={fileKeyword}
              onChange={(event) => setFileKeyword(event.target.value)}
              placeholder={t("aidpKnowledge.detailFileSearch")}
              style={{ width: 280, maxWidth: "100%" }}
            />
            <div className="flex items-center gap-2">
              <Tooltip title={t("aidpKnowledge.refresh")}>
                <Button
                  aria-label={t("aidpKnowledge.refresh")}
                  icon={<ReloadOutlined spin={loadingFiles} />}
                  onClick={() => void refreshFiles()}
                />
              </Tooltip>
              {canEdit && (
                <Button
                  disabled={selectedFileKeys.length === 0}
                  onClick={handleBatchDeleteFiles}
                >
                  {t("common.delete")}
                </Button>
              )}
              {canEdit && isAvailable && (
                <Button
                  type="primary"
                  icon={<UploadOutlined />}
                  onClick={() => setImportOpen(true)}
                >
                  {t("aidpKnowledge.importFile")}
                </Button>
              )}
            </div>
          </div>
          {fileError && (
            <Alert type="error" showIcon title={fileError} className="mb-4" />
          )}
          <div className="flex-1">
            <Table<AidpDocumentItem>
              rowKey={(record) => record.file_uuid || record.file_ino_no}
              columns={fileColumns}
              dataSource={files}
              loading={loadingFiles}
              rowSelection={
                canEdit
                  ? {
                      selectedRowKeys: selectedFileKeys,
                      onChange: (keys) => setSelectedFileKeys(keys),
                      // Rows already being deleted cannot be selected for
                      // another removal.
                      getCheckboxProps: (record) => ({
                        disabled: isFileDeleting(record.file_status),
                      }),
                    }
                  : undefined
              }
              pagination={false}
              components={{
                header: { cell: AidpResizableTitle },
              }}
              scroll={{ x: sumColumnWidths(fileColumns) }}
              locale={{
                emptyText: fileError ? null : (
                  <Empty description={t("aidpKnowledge.detailFilesEmpty")} />
                ),
              }}
              size="middle"
            />
          </div>
          <div className="mt-4 shrink-0 border-t border-gray-200 py-3">
            <AidpPagination
              currentPage={filePage}
              pageSize={filePageSize}
              total={fileTotal}
              totalReliable={fileTotalReliable}
              hasMore={fileHasMore}
              onPageChange={(page) =>
                setFileParams((current) => ({ ...current, page }))
              }
              onPageSizeChange={(pageSize) =>
                setFileParams((current) => ({ ...current, pageSize, page: 1 }))
              }
            />
          </div>
        </section>
      )}

      {activeTab === "tasks" && (
        <AidpKnowledgeTasksTab
          knowledgeBaseId={knowledgeBase.kds_id}
          canEdit={canEdit}
          // Tab-level dialogs mask the tab bar, so only the page-level edit
          // modal can be open while the tasks tab is mounted.
          pollingPaused={pollingPaused || editingKbMode !== null}
        />
      )}

      {activeTab === "information" && (
        <AidpKnowledgeInformationTab
          detail={detail}
          groupNames={groupNames}
          canConfigureGroupPermissions={canConfigureGroupPermissions}
          detailFetching={detailQuery.isFetching}
          onEditPermissions={() => setEditingKbMode("permissions")}
          onRefreshDetail={() => detailQuery.refetch()}
        />
      )}

      <AidpUpdateKbModal
        open={editingKbMode !== null}
        mode={editingKbMode || "metadata"}
        knowledgeBase={detail}
        onCancel={() => setEditingKbMode(null)}
        onSuccess={(updated) => {
          setEditingKbMode(null);
          onUpdated(updated);
          void detailQuery.refetch();
        }}
      />

      <AidpImportDrawer
        title={t("aidpKnowledge.importDrawerTitle")}
        open={importOpen}
        knowledgeBase={detail}
        onClose={() => {
          setImportOpen(false);
          void refreshFiles();
        }}
      />
    </div>
  );
};

export default AidpKnowledgeFilesPage;
