import React, { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Pagination, Tag, Upload, message, Tooltip } from "antd";
import {
  FileTextOutlined,
  InboxOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import type { AidpDocumentItem } from "@/ext_components/aidp/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { AIDP_ACCEPT_STRING } from "@/const/knowledgeBase";
import {
  AIDP_DOC_IN_PROGRESS_STATUSES,
  AIDP_DOCUMENT_STATUS,
  collectUploadedFileIds,
  normalizeAidpDocStatus,
} from "@/lib/aidpDocumentStatus";
import { partitionAidpFiles } from "@/services/uploadService";
import { getAidpUploadFailureDetails } from "@/ext_components/aidp/services/aidpUploadUtils";

const { Dragger } = Upload;

// AIDP rejects a re-uploaded file with a per-file reason, but that reason is
// shaped exactly like any other upload failure — the user cannot tell a
// duplicate apart from a genuine error. The wording AIDP actually returns is
// "文件已存在，请重命名或删除已有文件" / "File already exists. Please rename or
// delete the existing file.", which never contains the literal word
// "duplicate". Match on those phrases in BOTH languages (the backend returns
// reason_zh and reason_en together, independently of the UI language) plus the
// generic duplicate markers, case-insensitively so upstream capitalisation
// changes cannot silently break the detection.
const DUPLICATE_UPLOAD_REASON_MARKERS = [
  "already exists",
  "duplicate",
  "已存在",
  "重复",
];

const isDuplicateUploadReason = (
  ...reasons: Array<string | undefined>
): boolean => {
  const haystack = reasons
    .filter((reason): reason is string => Boolean(reason))
    .join(" ")
    .toLowerCase();
  if (!haystack) return false;
  return DUPLICATE_UPLOAD_REASON_MARKERS.some((marker) =>
    haystack.includes(marker)
  );
};

/** Table cell showing a document name above its AIDP file id. */
const DocumentNameCell: React.FC<{ fileName: string; fileInoNo: string }> = ({
  fileName,
  fileInoNo,
}) => (
  <td className="max-w-[280px] px-4 py-2">
    {/* `max-width` on a table cell is ignored by browsers, so the clamp must
        live on the inner div; the full value is surfaced on hover through an
        antd Tooltip instead of a width measurement. */}
    <Tooltip title={fileName}>
      <div className="max-w-[280px] truncate text-sm font-medium text-gray-800">
        {fileName}
      </div>
    </Tooltip>
    <Tooltip title={String(fileInoNo)}>
      <div className="mt-1 max-w-[280px] truncate text-xs text-gray-400">
        {fileInoNo}
      </div>
    </Tooltip>
  </td>
);

/**
 * Labels for the in-progress statuses, which all render as a blue tag.
 *
 * Uploading and extracting are the states a user watches right after an upload,
 * so they get the same treatment as processing instead of falling through to the
 * verbatim fallback below.
 */
const IN_PROGRESS_STATUS_LABELS: Record<string, string> = {
  [AIDP_DOCUMENT_STATUS.UPLOADING]: "aidpKnowledge.docStatusUploading",
  [AIDP_DOCUMENT_STATUS.PROCESSING]: "aidpKnowledge.docStatusProcessing",
  [AIDP_DOCUMENT_STATUS.EXTRACTING]: "aidpKnowledge.docStatusExtracting",
};

/**
 * Table cell showing the ingestion status of a document.
 *
 * Uploading, processing and extracting are blue because the file is still on its
 * way in (being uploaded, chunked/embedded, or having its content extracted) and
 * the list keeps refreshing itself until the status resolves; `COMPLETED` green
 * and `FAILED` red are the two terminal outcomes. A missing status means the
 * backend fell back to the completed-files listing, which only reports ingested
 * files — those render as a dash like any other empty cell. An unrecognised
 * status is shown verbatim rather than hidden, so a new AIDP status is visible
 * instead of silently blank.
 */
const DocumentStatusCell: React.FC<{ status?: string }> = ({ status }) => {
  const { t } = useTranslation();
  const normalized = normalizeAidpDocStatus(status);

  if (!normalized) {
    return <td className="px-4 py-2 text-sm text-gray-600">-</td>;
  }

  if (AIDP_DOC_IN_PROGRESS_STATUSES.includes(normalized)) {
    const labelKey = IN_PROGRESS_STATUS_LABELS[normalized];
    return (
      <td className="px-4 py-2">
        <Tag color="processing">{labelKey ? t(labelKey) : status}</Tag>
      </td>
    );
  }

  if (normalized === AIDP_DOCUMENT_STATUS.COMPLETED) {
    return (
      <td className="px-4 py-2">
        <Tag color="success">{t("aidpKnowledge.docStatusCompleted")}</Tag>
      </td>
    );
  }

  if (normalized === AIDP_DOCUMENT_STATUS.FAILED) {
    return (
      <td className="px-4 py-2">
        <Tag color="error">{t("aidpKnowledge.docStatusFailed")}</Tag>
      </td>
    );
  }

  return (
    <td className="px-4 py-2">
      <Tag>{status}</Tag>
    </td>
  );
};

interface AidpDocumentListProps {
  activeKb: AidpKnowledgeBaseItem | null;
  documents: AidpDocumentItem[];
  totalDocs: number;
  /** True when `totalDocs` came from the AIDP Count API. */
  totalReliable: boolean;
  hasMore: boolean;
  isLoading: boolean;
  currentPage: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  /** Called after an upload is accepted, with the ids AIDP returned for the
   *  accepted files. The parent uses them to keep refreshing the list until
   *  each uploaded file reports a terminal processing status. */
  onDocsUploaded: (uploadedFileIds: string[]) => void;
  onRefresh: () => void;
}

const AidpDocumentList: React.FC<AidpDocumentListProps> = ({
  activeKb,
  documents,
  totalDocs,
  totalReliable,
  hasMore,
  isLoading,
  currentPage,
  pageSize,
  onPageChange,
  onDocsUploaded,
  onRefresh,
}) => {
  const { t, i18n } = useTranslation();
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [downloadingFileUuid, setDownloadingFileUuid] = useState<string | null>(
    null
  );
  // Antd <Dragger> fires beforeUpload once per file in a multi-select batch.
  // The `fileList` array may-or-may-not be the same reference across the N
  // calls (behavior differs between <Upload> and <Dragger> and antd versions),
  // so we cannot rely on reference-equality for dedup. Instead, we collect
  // each file in beforeUpload and schedule a single requestAnimationFrame
  // flush: validation + upload run exactly ONCE per user selection.
  const pendingFilesRef = useRef<File[]>([]);
  const rafIdRef = useRef<number | null>(null);

  const isUnavailable =
    activeKb?.resource_status === "UNAVAILABLE" ||
    activeKb?.resource_status === "ORPHANED";
  const canDeleteDocuments =
    !!activeKb && !isUnavailable && activeKb.permission === "EDIT";
  const canDownloadDocuments =
    !!activeKb &&
    !isUnavailable &&
    (activeKb.permission === "EDIT" || activeKb.permission === "READ_ONLY");

  const handleDownload = useCallback(
    async (document: AidpDocumentItem) => {
      if (!activeKb || !document.file_uuid) return;
      setDownloadingFileUuid(document.file_uuid);
      try {
        const response = await aidpKnowledgeService.downloadDoc(
          activeKb.kds_id,
          document.file_uuid
        );
        const blob = await response.blob();
        const downloadUrl = URL.createObjectURL(blob);
        const link = window.document.createElement("a");
        link.href = downloadUrl;
        link.download = resolveDownloadFilename(response, document.file_name);
        link.click();
        URL.revokeObjectURL(downloadUrl);
        message.success(t("aidpKnowledge.downloadSuccess"));
      } catch (error) {
        log.error("Failed to download AIDP document:", error);
        message.error(t("aidpKnowledge.downloadFailed"));
      } finally {
        setDownloadingFileUuid(null);
      }
    },
    [activeKb, t]
  );

  const handleDelete = useCallback(
    (document: AidpDocumentItem) => {
      if (!activeKb || !document.file_uuid) return;
      Modal.confirm({
        title: t("aidpKnowledge.confirmDeleteDocTitle"),
        content: t("aidpKnowledge.confirmDeleteDocContent"),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        okButtonProps: { danger: true },
        centered: true,
        onOk: async () => {
          setDeleting(true);
          try {
            const result = await aidpKnowledgeService.removeDoc(
              activeKb.kds_id,
              document.file_uuid
            );
            if (result.summary.success > 0) {
              message.success(t("aidpKnowledge.deleteDocSuccess"));
            } else {
              message.error(t("aidpKnowledge.deleteDocFailed"));
            }
            if (result.summary.success > 0) {
              onDocsUploaded();
            }
          } catch (error) {
            log.error("Failed to delete AIDP document:", error);
            message.error(t("aidpKnowledge.deleteDocFailed"));
          } finally {
            setDeleting(false);
          }
        },
      });
    },
    [activeKb, onDocsUploaded, t]
  );

  const handleUpload = useCallback(
    async (fileList: File[]) => {
      if (!activeKb || fileList.length === 0) return;

      setUploading(true);
      try {
        const result = await aidpKnowledgeService.uploadDocs(
          activeKb.kds_id,
          fileList
        );

        const failureDetails = result.failed_list.map((item) => {
          // A duplicate is not an error the user can debug, so give it a
          // dedicated message instead of echoing AIDP's "please rename or
          // delete" instruction, which is not actionable in this dialog.
          if (isDuplicateUploadReason(item.reason_zh, item.reason_en)) {
            return t("aidpKnowledge.uploadDuplicateFile", {
              fileName: item.file_name,
            });
          }

          const reason = i18n.language.startsWith("zh")
            ? item.reason_zh || item.reason_en
            : item.reason_en || item.reason_zh;
          return `${item.file_name}: ${reason || t("aidpKnowledge.uploadFailed")}`;
        });
        const failureLines = failureDetails.map((detail, index) => (
          <div key={`${index}-${detail}`}>{detail}</div>
        ));

        if (result.summary.failed > 0 && result.summary.success === 0) {
          message.error(
            failureLines.length > 0 ? (
              <div className="text-left">{failureLines}</div>
            ) : (
              t("aidpKnowledge.uploadFailed")
            )
          );
        } else if (result.summary.failed > 0) {
          message.warning(
            <div className="text-left">
              <div>
                {t("aidpKnowledge.uploadPartial", {
                  success: result.summary.success,
                  failed: result.summary.failed,
                })}
              </div>
              {failureLines}
            </div>
          );
          onDocsUploaded(collectUploadedFileIds(result.success_list));
        } else {
          message.success(
            t("aidpKnowledge.uploadSuccess", { count: result.summary.success })
          );
          onDocsUploaded(collectUploadedFileIds(result.success_list));
        }
      } catch (error) {
        const reason =
          error instanceof Error && error.message.trim()
            ? error.message
            : t("aidpKnowledge.uploadFailed");
        message.error(reason);
      } finally {
        setUploading(false);
      }
    },
    [activeKb, i18n.language, onDocsUploaded, t]
  );

  const formatSize = (bytes?: number): string => {
    if (!bytes || bytes === 0) return "-";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024)
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  };

  const effectiveTotal = totalReliable
    ? totalDocs
    : hasMore
      ? currentPage * pageSize + 1
      : currentPage * pageSize;

  const canUpload =
    !!activeKb && !isUnavailable && activeKb.permission === "EDIT";

  const renderUploadArea = () => {
    if (!canUpload) {
      const reasonKey = !activeKb
        ? "aidpKnowledge.uploadNoKb"
        : isUnavailable
          ? "aidpKnowledge.uploadKbUnavailable"
          : "aidpKnowledge.uploadReadOnly";
      return (
        <div className="flex min-h-[150px] items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-6 text-center">
          <p className="text-sm text-gray-500">{t(reasonKey)}</p>
        </div>
      );
    }

    return (
      <Dragger
        accept={AIDP_ACCEPT_STRING}
        multiple
        showUploadList={false}
        beforeUpload={(_file) => {
          pendingFilesRef.current.push(_file);
          if (rafIdRef.current === null) {
            rafIdRef.current = requestAnimationFrame(() => {
              const batch = pendingFilesRef.current;
              pendingFilesRef.current = [];
              rafIdRef.current = null;

              const { valid } = partitionAidpFiles(batch, t, message);
              if (valid.length > 0) void handleUpload(valid);
            });
          }
          return false;
        }}
        disabled={uploading}
        className="!rounded-xl !border-blue-200 !bg-blue-50/30"
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined className="!text-blue-500" />
        </p>
        <p className="ant-upload-text !text-sm !text-gray-700">
          {uploading
            ? t("aidpKnowledge.uploading")
            : t("aidpKnowledge.uploadHint")}
        </p>
        <div className="ant-upload-hint mt-2 space-y-1 px-4 text-xs leading-5 text-gray-400">
          <div>{t("aidpKnowledge.uploadHintCount")}</div>
          <div>{t("aidpKnowledge.uploadHintSize")}</div>
          <div className="break-all">
            {t("aidpKnowledge.uploadHintFormats")}
          </div>
        </div>
      </Dragger>
    );
  };

  return (
    <div className="w-full bg-white border border-gray-200 rounded-md overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Tooltip title={activeKb?.kds_name || ""}>
              <h3 className="min-w-0 text-base font-semibold text-blue-500 truncate">
                {activeKb?.kds_name || ""}
              </h3>
            </Tooltip>
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-600 border border-gray-200">
              {t("aidpKnowledge.tagDocs", { count: totalDocs })}
            </span>
          </div>
        </div>
        <Tooltip title={t("aidpKnowledge.refresh")}>
          <Button
            aria-label={t("aidpKnowledge.refresh")}
            className="!h-10 !w-10 !rounded-lg !p-0"
            icon={<ReloadOutlined spin={isLoading || uploading} />}
            onClick={onRefresh}
            disabled={!activeKb || uploading}
          />
        </Tooltip>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-6 py-5">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="text-center">
              <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-blue-100 border-b-blue-500" />
              <p className="text-sm text-gray-500">
                {t("aidpKnowledge.loadingDocs")}
              </p>
            </div>
          </div>
        ) : documents.length > 0 ? (
          <div className="overflow-hidden rounded-xl border border-gray-200">
            <table className="min-w-full bg-white">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                    {t("aidpKnowledge.docFileName")}
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                    {t("aidpKnowledge.docType")}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docStatus")}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docSize")}
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                    {t("aidpKnowledge.docCreatedAt")}
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">
                    {t("aidpKnowledge.docActions")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {documents.map((doc) => (
                  <tr key={doc.file_ino_no} className="hover:bg-gray-50">
                    <DocumentNameCell
                      fileName={doc.file_name}
                      fileInoNo={doc.file_ino_no}
                    />
                    <td className="px-4 py-2 text-sm text-gray-600">
                      {doc.file_type || "-"}
                    </td>
                    <DocumentStatusCell status={doc.status} />
                    <td className="px-4 py-2 text-sm text-gray-600">
                      {formatSize(doc.file_size)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {doc.created_at
                        ? new Date(doc.created_at).toLocaleString()
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-2">
                        {canDownloadDocuments && (
                          <Button
                            type="link"
                            size="small"
                            loading={downloadingFileUuid === doc.file_uuid}
                            disabled={!doc.file_uuid}
                            onClick={() => void handleDownload(doc)}
                          >
                            {t("aidpKnowledge.download")}
                          </Button>
                        )}
                        {canDeleteDocuments && (
                          <Button
                            type="link"
                            danger
                            size="small"
                            disabled={!doc.file_uuid || deleting}
                            onClick={() => handleDelete(doc)}
                          >
                            {t("aidpKnowledge.delete")}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex min-h-[180px] items-center justify-center rounded-xl border border-dashed border-gray-200 text-sm text-gray-400">
            {t("aidpKnowledge.noDocuments")}
          </div>
        )}
      </div>

      {documents.length > 0 && (
        <div className="flex shrink-0 justify-center border-t border-gray-100 px-6 py-4">
          <Pagination
            current={currentPage}
            pageSize={pageSize}
            total={effectiveTotal || 1}
            onChange={onPageChange}
            showSizeChanger={false}
            simple={!totalReliable}
            showTotal={
              totalReliable
                ? (count) => t("aidpKnowledge.showTotal", { count })
                : undefined
            }
            size="small"
          />
        </div>
      )}

      <div className="shrink-0 border-t border-gray-100 px-6 py-5">
        {renderUploadArea()}
      </div>
    </div>
  );
};

export default AidpDocumentList;
