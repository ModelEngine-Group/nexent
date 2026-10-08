"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  App,
  Breadcrumb,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Skeleton,
  Table,
  Tabs,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  ClockCircleOutlined,
  CloseOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  InfoCircleOutlined,
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
  formatAidpDocumentCount,
} from "@/lib/aidpKnowledgeDisplay";
import { useAidpGroupOptions } from "../hooks/useAidpGroupOptions";
import AidpPagination from "./AidpPagination";
import AidpDocumentList from "./AidpDocumentList";
import AidpUpdateKbModal from "./AidpUpdateKbModal";
import AidpKnowledgeDetailInformation, {
  AidpDetailField,
} from "./AidpKnowledgeDetailInformation";

type DetailTab = "files" | "tasks" | "information";
type TaskFilter = 0 | 1 | 2 | 3 | 4 | 5;

interface AidpKnowledgeDetailProps {
  knowledgeBase: AidpKnowledgeBaseItem;
  onBack: () => void;
  onDelete: (knowledgeBase: AidpKnowledgeBaseItem) => void;
  onUpdated: (knowledgeBase: AidpKnowledgeBaseItem) => void;
}

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

const formatFailureTaskDateTime = (value: unknown): string => {
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
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
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

const statusCode = (status: AidpDocumentItem["status"]): number | null => {
  if (typeof status === "number") return status;
  if (typeof status === "string" && /^\d+$/.test(status.trim())) {
    return Number(status);
  }
  const aliases: Record<string, number> = {
    COMPLETED: 1,
    SUCCESS: 1,
    PROCESSING: 2,
    EXTRACTING: 2,
    FAILED: 3,
    VECTOR_INGESTION_FAILED: 3,
    UPLOADING: 4,
    QUEUED: 4,
    GRAPH_INGESTION_FAILED: 5,
  };
  return typeof status === "string"
    ? (aliases[status.toUpperCase()] ?? null)
    : null;
};

const graphConfigOf = (detail: AidpKbDetail): Record<string, unknown> => {
  const raw = detail.graph_config;
  if (raw && typeof raw === "object") return raw;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw) as unknown;
      return parsed && typeof parsed === "object"
        ? (parsed as Record<string, unknown>)
        : {};
    } catch {
      return {};
    }
  }
  return {};
};

const AidpKnowledgeDetail: React.FC<AidpKnowledgeDetailProps> = ({
  knowledgeBase,
  onBack,
  onDelete,
  onUpdated,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { groupOptions } = useAidpGroupOptions();
  const [activeTab, setActiveTab] = useState<DetailTab>("files");
  const [detail, setDetail] = useState<AidpKbDetail>(knowledgeBase);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [editingMetadata, setEditingMetadata] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [savingSetting, setSavingSetting] = useState(false);
  const [settingModal, setSettingModal] = useState<
    "chunk_mode" | "topk" | null
  >(null);
  const [settingForm] = Form.useForm<{ value: number }>();

  const [fileKeyword, setFileKeyword] = useState("");
  const [files, setFiles] = useState<AidpDocumentItem[]>([]);
  const [fileTotal, setFileTotal] = useState(0);
  const [fileHasMore, setFileHasMore] = useState(false);
  const [fileTotalReliable, setFileTotalReliable] = useState(true);
  const [filePage, setFilePage] = useState(1);
  const [filePageSize, setFilePageSize] = useState(PAGE_SIZE);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [taskKeyword, setTaskKeyword] = useState("");
  const [taskStatus, setTaskStatus] = useState<TaskFilter>(0);
  const [tasks, setTasks] = useState<AidpDocumentItem[]>([]);
  const [taskTotal, setTaskTotal] = useState(0);
  const [taskStats, setTaskStats] = useState({
    total: 0,
    extracting: 0,
    failed: 0,
    success: 0,
    queued: 0,
  });
  const [taskPage, setTaskPage] = useState(1);
  const [taskPageSize, setTaskPageSize] = useState(PAGE_SIZE);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [failureTask, setFailureTask] = useState<AidpDocumentItem | null>(null);
  const [retryingFileUuid, setRetryingFileUuid] = useState<string | null>(null);
  const graphConfig = useMemo(() => graphConfigOf(detail), [detail]);
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
    setLoadingDetail(true);
    try {
      const result = await aidpKnowledgeService.getKb(knowledgeBase.kds_id);
      const merged = { ...knowledgeBase, ...result } as AidpKbDetail;
      setDetail(merged);
      onUpdated(merged as AidpKnowledgeBaseItem);
    } catch {
      message.error(t("aidpKnowledge.detailLoadFailed"));
    } finally {
      setLoadingDetail(false);
    }
  }, [knowledgeBase, message, onUpdated, t]);

  const fetchFiles = useCallback(
    async (page = 1, keyword = fileKeyword, pageSize = filePageSize) => {
      setLoadingFiles(true);
      try {
        const result = await aidpKnowledgeService.listIngestedFiles(
          knowledgeBase.kds_id,
          page,
          pageSize,
          keyword
        );
        setFiles(result.value);
        setFileTotal(result.total_count ?? result.value.length);
        setFileHasMore(result.has_more ?? false);
        setFileTotalReliable(result.total_reliable !== false);
        setFilePage(page);
      } catch {
        message.error(t("aidpKnowledge.detailFilesLoadFailed"));
        setFiles([]);
        setFileTotal(0);
        setFileHasMore(false);
        setFileTotalReliable(false);
      } finally {
        setLoadingFiles(false);
      }
    },
    [fileKeyword, filePageSize, knowledgeBase.kds_id, message, t]
  );

  const fetchTasks = useCallback(
    async (
      page = 1,
      keyword = taskKeyword,
      status = taskStatus,
      pageSize = taskPageSize,
      silent = false
    ) => {
      if (!silent) setLoadingTasks(true);
      try {
        const result = await aidpKnowledgeService.listUploadTasks(
          knowledgeBase.kds_id,
          page,
          pageSize,
          keyword,
          status
        );
        setTasks(result.value);
        setTaskTotal(result.total_count);
        setTaskStats(result.stats);
        setTaskPage(page);
      } catch {
        if (!silent) message.error(t("aidpKnowledge.detailTasksLoadFailed"));
        setTasks([]);
        setTaskTotal(0);
      } finally {
        if (!silent) setLoadingTasks(false);
      }
    },
    [knowledgeBase.kds_id, message, taskKeyword, taskPageSize, taskStatus, t]
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshDetail();
      void fetchFiles(1, "", PAGE_SIZE);
      void fetchTasks(1, "", 0, PAGE_SIZE);
    }, 0);
    return () => window.clearTimeout(timer);
    // The parent remounts this component when the selected KB id changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [knowledgeBase.kds_id]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetchFiles(1, fileKeyword.trim(), filePageSize);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [fileKeyword, filePageSize, fetchFiles]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetchTasks(1, taskKeyword.trim(), taskStatus, taskPageSize);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [taskKeyword, taskStatus, taskPageSize, fetchTasks]);

  useEffect(() => {
    if (
      activeTab !== "tasks" ||
      taskStats.extracting + taskStats.queued === 0
    ) {
      return;
    }
    const timer = window.setInterval(() => {
      void fetchTasks(taskPage, taskKeyword, taskStatus, taskPageSize, true);
    }, 10000);
    return () => window.clearInterval(timer);
  }, [
    activeTab,
    fetchTasks,
    taskKeyword,
    taskPage,
    taskPageSize,
    taskStats.extracting,
    taskStats.queued,
    taskStatus,
  ]);

  const uploadComplete = useCallback(() => {
    setImportOpen(false);
    void fetchFiles(1, fileKeyword, filePageSize);
    void fetchTasks(1, taskKeyword, taskStatus, taskPageSize);
    void refreshDetail();
  }, [
    fetchFiles,
    fetchTasks,
    fileKeyword,
    filePageSize,
    refreshDetail,
    taskKeyword,
    taskPageSize,
    taskStatus,
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
      } catch {
        message.error(t("aidpKnowledge.downloadFailed"));
      }
    },
    [knowledgeBase.kds_id, message, t]
  );

  const handleDeleteFile = useCallback(
    (file: AidpDocumentItem) => {
      Modal.confirm({
        title: t("aidpKnowledge.deleteDocTitle"),
        content: file.file_name,
        okButtonProps: { danger: true },
        onOk: async () => {
          try {
            await aidpKnowledgeService.removeDoc(
              knowledgeBase.kds_id,
              file.file_uuid
            );
            message.success(t("aidpKnowledge.deleteDocSuccess"));
            void fetchFiles(filePage, fileKeyword, filePageSize);
            void refreshDetail();
          } catch {
            message.error(t("aidpKnowledge.deleteDocFailed"));
          }
        },
      });
    },
    [
      fetchFiles,
      fileKeyword,
      filePage,
      filePageSize,
      knowledgeBase.kds_id,
      message,
      refreshDetail,
      t,
    ]
  );

  const handleRetry = useCallback(
    async (task: AidpDocumentItem) => {
      if (!task.file_uuid) return;
      setRetryingFileUuid(task.file_uuid);
      try {
        const result = await aidpKnowledgeService.retryUploadTasks(
          knowledgeBase.kds_id,
          [task.file_uuid]
        );
        if (result.summary.failed > 0) {
          message.error(t("aidpKnowledge.retryTaskFailed"));
        } else {
          message.success(t("aidpKnowledge.retryTaskSuccess"));
          setFailureTask(null);
          void fetchTasks(taskPage, taskKeyword, taskStatus, taskPageSize);
        }
      } catch {
        message.error(t("aidpKnowledge.retryTaskFailed"));
      } finally {
        setRetryingFileUuid(null);
      }
    },
    [
      fetchTasks,
      knowledgeBase.kds_id,
      message,
      taskKeyword,
      taskPage,
      taskPageSize,
      taskStatus,
      t,
    ]
  );

  const saveSetting = async () => {
    if (!settingModal) return;
    const values = await settingForm.validateFields();
    setSavingSetting(true);
    try {
      await aidpKnowledgeService.updateKb(knowledgeBase.kds_id, {
        [settingModal]: values.value,
      });
      setSettingModal(null);
      await refreshDetail();
      message.success(t("aidpKnowledge.detailSettingSaved"));
    } catch {
      message.error(t("aidpKnowledge.detailSettingSaveFailed"));
    } finally {
      setSavingSetting(false);
    }
  };

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
      dataIndex: "import_mode",
      key: "import_mode",
      width: 120,
      ellipsis: true,
      render: (value?: string) => value || UNKNOWN,
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
              danger
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

  const taskColumns: ColumnsType<AidpDocumentItem> = [
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
            <Button
              type="link"
              size="small"
              className="px-0"
              loading={retryingFileUuid === record.file_uuid}
              onClick={() => void handleRetry(record)}
            >
              {t("aidpKnowledge.retryTask")}
            </Button>
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

  const privateScope = detail.ingroup_permission === "PRIVATE";
  const taskStatusOptions = [
    { value: 0, label: t("aidpKnowledge.taskAll") },
    { value: 1, label: t("aidpKnowledge.taskSuccess") },
    { value: 2, label: t("aidpKnowledge.taskExtracting") },
    { value: 3, label: t("aidpKnowledge.taskVectorFailed") },
    { value: 4, label: t("aidpKnowledge.taskQueued") },
    { value: 5, label: t("aidpKnowledge.taskGraphFailed") },
  ];
  const descriptionValue = (value: unknown): string => {
    if (value === undefined || value === null || value === "") return UNKNOWN;
    if (typeof value === "boolean")
      return value ? t("common.yes") : t("common.no");
    return String(value);
  };

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
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-2xl text-violet-600">
              <DatabaseOutlined />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <h1 className="truncate text-lg font-semibold text-gray-800">
                  {detail.kds_name}
                </h1>
                {canEdit && (
                  <Tooltip title={t("aidpKnowledge.detailEditNameDescription")}>
                    <Button
                      type="text"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => setEditingMetadata(true)}
                    />
                  </Tooltip>
                )}
              </div>
              <p className="mt-1 truncate text-sm leading-6 text-gray-600">
                {detail.description || t("aidpKnowledge.noDescription")}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {canEdit && (
              <Button
                danger
                icon={<DeleteOutlined />}
                onClick={() => onDelete(knowledgeBase)}
              >
                {t("common.delete")}
              </Button>
            )}
          </div>
        </div>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 @min-[600px]:grid-cols-2 @min-[850px]:grid-cols-5">
          <div className="flex min-w-0 items-center gap-3">
            <FileTextOutlined className="rounded-lg bg-violet-100 p-2 text-base text-violet-600" />
            <AidpDetailField label={t("aidpKnowledge.detailTabFiles")}>
              {formatAidpDocumentCount(
                detail.document_count,
                detail.document_count_reliable
              )}
            </AidpDetailField>
          </div>
          <div className="flex min-w-0 items-center gap-3">
            <DatabaseOutlined className="rounded-lg bg-violet-100 p-2 text-base text-violet-600" />
            <AidpDetailField label={t("aidpKnowledge.detailPermissions")}>
              {privateScope
                ? t("aidpKnowledge.scopePrivate")
                : t("aidpKnowledge.scopeShared")}
            </AidpDetailField>
          </div>
          <div className="flex min-w-0 items-center gap-3">
            <TeamOutlined className="rounded-lg bg-violet-100 p-2 text-base text-violet-600" />
            <AidpDetailField label={t("aidpKnowledge.detailAllowedGroups")}>
              {privateScope
                ? t("aidpKnowledge.detailOwnerOnly")
                : groupNames.length > 0
                  ? groupNames.join("、")
                  : (detail.group_ids || []).join("、") || UNKNOWN}
            </AidpDetailField>
          </div>
          <div className="flex min-w-0 items-center gap-3">
            <ClockCircleOutlined className="rounded-lg bg-violet-100 p-2 text-base text-violet-600" />
            <AidpDetailField label={t("aidpKnowledge.detailCreatedAt")}>
              {formatDetailDateTime(detail.created_at)}
            </AidpDetailField>
          </div>
          <div className="flex min-w-0 items-center gap-3">
            <UserOutlined className="rounded-lg bg-violet-100 p-2 text-base text-violet-600" />
            <AidpDetailField label={t("aidpKnowledge.detailCreator")}>
              {detail.created_by || detail.user_name || UNKNOWN}
            </AidpDetailField>
          </div>
        </dl>
      </section>

      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as DetailTab)}
        className="shrink-0 [&>.ant-tabs-nav]:mb-0 [&>.ant-tabs-content-holder]:hidden"
        tabBarStyle={{ marginBottom: 0 }}
        items={[
          { key: "files", label: t("aidpKnowledge.detailTabFiles") },
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
                  onClick={() =>
                    void fetchFiles(filePage, fileKeyword, filePageSize)
                  }
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
          <div className="flex-1">
            <Table<AidpDocumentItem>
              rowKey={(record) => record.file_uuid || record.file_ino_no}
              columns={fileColumns}
              dataSource={files}
              loading={loadingFiles}
              pagination={false}
              scroll={{ x: 930 }}
              locale={{
                emptyText: (
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
                void fetchFiles(page, fileKeyword, filePageSize)
              }
              onPageSizeChange={(size) => setFilePageSize(size)}
            />
          </div>
        </section>
      )}

      {activeTab === "tasks" && (
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
              <Select<TaskFilter>
                value={taskStatus}
                options={taskStatusOptions}
                onChange={(value) => setTaskStatus(value)}
                style={{ width: 136, maxWidth: "100%" }}
                aria-label={t("aidpKnowledge.detailTaskStatus")}
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
                onClick={() =>
                  void fetchTasks(
                    taskPage,
                    taskKeyword,
                    taskStatus,
                    taskPageSize
                  )
                }
              />
            </Tooltip>
          </div>
          <div className="flex-1">
            <Table<AidpDocumentItem>
              rowKey={(record) => record.file_uuid || record.file_ino_no}
              columns={taskColumns}
              dataSource={tasks}
              loading={loadingTasks}
              pagination={false}
              scroll={{ x: 885 }}
              locale={{
                emptyText: (
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
              totalReliable
              hasMore={taskPage * taskPageSize < taskTotal}
              onPageChange={(page) =>
                void fetchTasks(page, taskKeyword, taskStatus, taskPageSize)
              }
              onPageSizeChange={(size) => setTaskPageSize(size)}
            />
          </div>
        </section>
      )}

      {activeTab === "information" &&
        (loadingDetail ? (
          <Skeleton active className="shrink-0" paragraph={{ rows: 5 }} />
        ) : (
          <AidpKnowledgeDetailInformation
            detail={detail}
            graphConfig={graphConfig}
            groupNames={groupNames}
            formatDateTime={formatDetailDateTime}
            onEditMetadata={() => setEditingMetadata(true)}
            onEditSetting={(setting) => {
              settingForm.setFieldsValue({
                value:
                  setting === "chunk_mode"
                    ? (detail.chunk_mode ?? 0)
                    : (detail.topk ?? 10),
              });
              setSettingModal(setting);
            }}
          />
        ))}

      <AidpUpdateKbModal
        open={editingMetadata}
        knowledgeBase={detail as AidpKnowledgeBaseItem}
        onCancel={() => setEditingMetadata(false)}
        onSuccess={(updated) => {
          setEditingMetadata(false);
          setDetail((current) => ({ ...current, ...updated }));
          onUpdated(updated);
          void refreshDetail();
        }}
      />

      <Modal
        title={t(
          settingModal === "chunk_mode"
            ? "aidpKnowledge.detailEditChunkMode"
            : "aidpKnowledge.detailEditTopK"
        )}
        open={Boolean(settingModal)}
        onCancel={() => setSettingModal(null)}
        onOk={() => void saveSetting()}
        confirmLoading={savingSetting}
        destroyOnClose
      >
        {settingModal && (
          <Form
            form={settingForm}
            layout="vertical"
            initialValues={{ value: 0 }}
          >
            <Form.Item
              name="value"
              label={t(
                settingModal === "chunk_mode"
                  ? "aidpKnowledge.detailChunkMode"
                  : "aidpKnowledge.detailVectorTopK"
              )}
              rules={[{ required: true }]}
            >
              {settingModal === "chunk_mode" ? (
                <Select
                  options={[
                    { value: 0, label: t("aidpKnowledge.chunkModeSmart") },
                    { value: 1, label: t("aidpKnowledge.chunkModeLegal") },
                  ]}
                />
              ) : (
                <InputNumber min={1} max={100} className="w-full" />
              )}
            </Form.Item>
          </Form>
        )}
      </Modal>

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
        width={640}
        styles={{
          header: { padding: "0 20px" },
          body: { padding: "16px 20px" },
        }}
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

      <Modal
        title={t("aidpKnowledge.importFileTitle", { name: detail.kds_name })}
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        footer={null}
        destroyOnClose
        width={760}
        centered
      >
        <AidpDocumentList
          activeKb={knowledgeBase}
          documents={[]}
          totalDocs={0}
          totalReliable={false}
          hasMore={false}
          isLoading={false}
          currentPage={1}
          pageSize={PAGE_SIZE}
          onPageChange={() => undefined}
          onDocsUploaded={uploadComplete}
          onRefresh={() => void fetchFiles(filePage, fileKeyword, filePageSize)}
          uploadOnly
        />
      </Modal>
    </div>
  );
};

export default AidpKnowledgeDetail;
