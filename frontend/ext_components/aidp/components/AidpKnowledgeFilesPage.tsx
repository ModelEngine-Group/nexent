"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  App,
  Alert,
  Breadcrumb,
  Button,
  Empty,
  Input,
  Modal,
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

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import aidpKnowledgeService, {
  type AidpDocumentItem,
  type AidpKbDetail,
} from "@/ext_components/aidp/services/aidpKnowledgeService";
import {
  AIDP_UNKNOWN_VALUE,
  formatAidpCreator,
  formatAidpDocumentCount,
} from "@/lib/aidpKnowledgeDisplay";
import { useAidpGroupOptions } from "../hooks/useAidpGroupOptions";
import { useAidpKnowledgeFiles } from "../hooks/useAidpKnowledgeQueries";
import { getAidpErrorMessage } from "../services/aidpErrorUtils";
import { ApiError } from "@/services/api";
import AidpPagination from "./AidpPagination";
import AidpImportDrawer from "./AidpImportDrawer";
import AidpUpdateKbModal from "./AidpUpdateKbModal";
import AidpGroupNamesDisplay from "./AidpGroupNamesDisplay";

interface AidpKnowledgeFilesPageProps {
  knowledgeBase: AidpKnowledgeBaseItem;
  onBack: () => void;
  onDelete: (knowledgeBase: AidpKnowledgeBaseItem) => void;
  onUpdated: (knowledgeBase: AidpKnowledgeBaseItem) => void;
}

const AidpDetailField = ({
  label,
  children,
  className = "",
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) => (
  <div className={`min-w-0 ${className}`}>
    <dt className="mb-1 min-h-5 text-xs leading-5 text-gray-500">{label}</dt>
    <dd className="m-0 min-h-6 break-words text-sm leading-6 text-gray-800">
      {children}
    </dd>
  </div>
);

const PAGE_SIZE = 10;
const UNKNOWN = AIDP_UNKNOWN_VALUE;

const formatDetailDateTime = (value: unknown): string => {
  let date: Date;
  if (typeof value === "number" && Number.isFinite(value)) {
    date = new Date(value < 1e12 ? value * 1000 : value);
  } else if (typeof value === "string" && value.trim()) {
    const normalized = value.trim();
    const numeric = /^\d+(?:\.\d+)?$/.test(normalized)
      ? Number(normalized)
      : null;
    date =
      numeric === null
        ? new Date(normalized)
        : new Date(numeric < 1e12 ? numeric * 1000 : numeric);
  } else {
    return UNKNOWN;
  }
  if (Number.isNaN(date.getTime())) return UNKNOWN;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
};

const formatFileSize = (bytes?: number): string => {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) {
    return UNKNOWN;
  }
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
};

const AidpKnowledgeFilesPage: React.FC<AidpKnowledgeFilesPageProps> = ({
  knowledgeBase,
  onBack,
  onDelete,
  onUpdated,
}) => {
  const { t, i18n } = useTranslation();
  const { message } = App.useApp();
  const { groupOptions } = useAidpGroupOptions();
  const [detail, setDetail] = useState<AidpKbDetail>(knowledgeBase);
  const [editingKbMode, setEditingKbMode] = useState<
    "metadata" | "permissions" | null
  >(null);
  const [importOpen, setImportOpen] = useState(false);
  const [fileKeyword, setFileKeyword] = useState("");
  const [fileParams, setFileParams] = useState({
    page: 1,
    pageSize: PAGE_SIZE,
    keyword: "",
  });
  const { page: filePage, pageSize: filePageSize } = fileParams;
  const filesQuery = useAidpKnowledgeFiles(
    knowledgeBase.kds_id,
    filePage,
    filePageSize,
    fileParams.keyword
  );
  const files = filesQuery.data?.value ?? [];
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
  const groupNames = useMemo(() => {
    const names = new Map(
      groupOptions.map((option) => [option.value, option.label])
    );
    return (detail.group_ids || [])
      .map((id) => names.get(id))
      .filter((name): name is string => Boolean(name));
  }, [detail.group_ids, groupOptions]);
  const canEdit = detail.permission === "EDIT";
  const isAvailable =
    detail.resource_status !== "UNAVAILABLE" &&
    detail.resource_status !== "ORPHANED";

  const refreshDetail = useCallback(async () => {
    try {
      const result = await aidpKnowledgeService.getKb(knowledgeBase.kds_id);
      const merged = { ...knowledgeBase, ...result } as AidpKbDetail;
      setDetail(merged);
      onUpdated(merged as AidpKnowledgeBaseItem);
    } catch (error) {
      message.error(
        getAidpErrorMessage(error, t, t("aidpKnowledge.detailLoadFailed"))
      );
    }
  }, [knowledgeBase, message, onUpdated, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshDetail();
    }, 0);
    return () => window.clearTimeout(timer);
    // The parent remounts this component when the selected KB id changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [knowledgeBase.kds_id]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const keyword = fileKeyword.trim();
      setFileParams((current) =>
        current.keyword === keyword ? current : { ...current, keyword, page: 1 }
      );
    }, 250);
    return () => window.clearTimeout(timer);
  }, [fileKeyword]);

  const refreshFiles = useCallback(async () => {
    const result = await refetchFiles({ cancelRefetch: false });
    if (!result.isSuccess || result.data.value.length > 0 || filePage <= 1)
      return;
    const lastPage =
      result.data.total_reliable !== false &&
      result.data.total_count !== undefined
        ? Math.max(1, Math.ceil(result.data.total_count / filePageSize))
        : filePage - 1;
    setFileParams((current) =>
      current.page === filePage &&
      current.pageSize === filePageSize &&
      current.keyword === fileParams.keyword
        ? { ...current, page: Math.min(filePage - 1, lastPage) }
        : current
    );
  }, [refetchFiles, filePage, filePageSize, fileParams.keyword]);

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
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.downloadFailed"))
        );
      }
    },
    [knowledgeBase.kds_id, message, t]
  );

  const handleDeleteFile = useCallback(
    (file: AidpDocumentItem) => {
      Modal.confirm({
        title: t("aidpKnowledge.deleteDocTitle"),
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
            void refreshDetail();
          } catch (error) {
            message.error(
              getAidpErrorMessage(error, t, t("aidpKnowledge.deleteDocFailed"))
            );
            throw error;
          }
        },
      });
    },
    [
      refreshFiles,
      i18n.language,
      knowledgeBase.kds_id,
      message,
      refreshDetail,
      t,
    ]
  );

  const fileColumns: ColumnsType<AidpDocumentItem> = [
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
              onClick={() => handleDeleteFile(record)}
            >
              {t("common.delete")}
            </Button>
          )}
        </div>
      ),
    },
  ];

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
              {canEdit && (
                <Button
                  icon={<DeleteOutlined />}
                  onClick={() => onDelete(knowledgeBase)}
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
                    detail.document_count,
                    detail.document_count_reliable
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
                  ) : groupNames.length > 0 ||
                    (detail.group_ids || []).length > 0 ? (
                    <AidpGroupNamesDisplay
                      groupNames={
                        groupNames.length > 0
                          ? groupNames
                          : (detail.group_ids || []).map(String)
                      }
                    />
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
                  {formatAidpCreator(detail.creator_name)}
                </AidpDetailField>
              </div>
            </dl>
          </div>
        </div>
      </section>

      <Tabs
        activeKey="files"
        className="shrink-0 [&>.ant-tabs-nav]:mb-0 [&>.ant-tabs-content-holder]:hidden"
        tabBarStyle={{ marginBottom: 0 }}
        items={[{ key: "files", label: t("aidpKnowledge.detailTabFiles") }]}
      />

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
            pagination={false}
            scroll={{ x: 930 }}
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

      <AidpUpdateKbModal
        open={editingKbMode !== null}
        mode={editingKbMode || "metadata"}
        knowledgeBase={detail as AidpKnowledgeBaseItem}
        onCancel={() => setEditingKbMode(null)}
        onSuccess={(updated) => {
          setEditingKbMode(null);
          setDetail((current) => ({ ...current, ...updated }));
          onUpdated(updated);
          void refreshDetail();
        }}
      />

      <AidpImportDrawer
        title={t("aidpKnowledge.importDrawerTitle")}
        open={importOpen}
        knowledgeBase={knowledgeBase}
        onClose={() => {
          setImportOpen(false);
          void refreshFiles();
          void refreshDetail();
        }}
        onDocsUploaded={() => undefined}
        onRefresh={() => undefined}
      />
    </div>
  );
};

export default AidpKnowledgeFilesPage;
