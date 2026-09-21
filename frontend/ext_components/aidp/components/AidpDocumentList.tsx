import React, { useState, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";

import { Button, Pagination, Tag, Upload, message, Tooltip } from "antd";
import {
  UploadOutlined,
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
  /** True when `totalDocs` came from the AIDP Count API; when false the
   *  total is a fallback estimate and "共 N 条" should be suppressed. */
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
  // Antd <Dragger> fires beforeUpload once per file in a multi-select batch.
  // The `fileList` array may-or-may-not be the same reference across the N
  // calls (behavior differs between <Upload> and <Dragger> and antd versions),
  // so we cannot rely on reference-equality for dedup. Instead, we collect
  // each file in beforeUpload and schedule a single requestAnimationFrame
  // flush: validation + upload run exactly ONCE per user selection.
  const pendingFilesRef = useRef<File[]>([]);
  const rafIdRef = useRef<number | null>(null);

  const handleUpload = useCallback(
    async (fileList: File[]) => {
      if (!activeKb) return;
      if (fileList.length === 0) return;

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

  // Format file size for display
  const formatSize = (bytes?: number): string => {
    if (!bytes || bytes === 0) return "-";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024)
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
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
          <Tooltip title={t("aidpKnowledge.refresh")}>
            <Button
              icon={<ReloadOutlined spin={isLoading} />}
              onClick={onRefresh}
              size="small"
              disabled={!activeKb}
            />
          </Tooltip>
        </div>
      </div>

      {/* Document table */}
      <div className="p-2 border-b border-gray-200">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2" />
              <p className="text-sm text-gray-600">
                {t("aidpKnowledge.loadingDocs")}
              </p>
            </div>
          </div>
        ) : documents.length > 0 ? (
          <div className="overflow-hidden border border-gray-200 rounded-md">
            <table className="min-w-full bg-white">
              <thead className="bg-gray-50 sticky top-0 z-10">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docFileName")}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docType")}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docStatus")}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docSize")}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docCreatedAt")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
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
                    <td className="px-4 py-2 text-sm text-gray-600">
                      {doc.created_at
                        ? new Date(doc.created_at).toLocaleString()
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex items-center justify-center py-8 text-gray-500 text-sm">
            {t("aidpKnowledge.noDocuments")}
          </div>
        )}
      </div>

      {/* Server-side pagination.
          AIDP exposes a dedicated Count API for documents which the backend
          now calls alongside the list request. When Count succeeds,
          `totalReliable` is true and we display the full pagination (page
          numbers + "共 N 条"). When Count fails (e.g. the endpoint is not
          available on a particular AIDP instance), `totalReliable` is false
          and we fall back to simple prev/next mode without a total, using
          `has_more` to decide whether the next-page button should enable. */}
      {documents.length > 0 &&
        (() => {
          // When total is unreliable we still need antd to know when to
          // enable "next": set total just past the current page if there is
          // a next page, otherwise clamp to the current page end.
          const effectiveTotal = totalReliable
            ? totalDocs
            : hasMore
              ? currentPage * pageSize + 1
              : currentPage * pageSize;
          return (
            <div className="px-4 py-2 border-b border-gray-200 flex justify-center">
              <Pagination
                current={currentPage}
                pageSize={pageSize}
                total={effectiveTotal || 1}
                onChange={onPageChange}
                showSizeChanger={false}
                simple={!totalReliable}
                showTotal={
                  totalReliable
                    ? (total) => t("aidpKnowledge.showTotal", { count: total })
                    : undefined
                }
                size="small"
              />
            </div>
          );
        })()}

      {/* Upload area — gated by ``activeKb.permission`` and ``resource_status``.

          Per v7.1 §7.1, READ_ONLY callers may view existing documents but
          must not be able to upload. UNAVAILABLE / ORPHANED KBs are
          read-only regardless of permission because the AIDP backend cannot
          service the request. The container is replaced with a hint instead
          of disabling the Dragger so the visual structure stays consistent
          and screen-reader users get an explicit reason. */}
      <div className="p-3">
        {(() => {
          const isUnavailable =
            activeKb?.resource_status === "UNAVAILABLE" ||
            activeKb?.resource_status === "ORPHANED";
          const canUpload =
            !!activeKb && !isUnavailable && activeKb.permission === "EDIT";
          if (!canUpload) {
            const reasonKey = !activeKb
              ? "aidpKnowledge.uploadNoKb"
              : isUnavailable
                ? "aidpKnowledge.uploadKbUnavailable"
                : "aidpKnowledge.uploadReadOnly";
            return (
              <div className="ant-upload ant-upload-drag p-6 text-center border border-dashed border-gray-200 rounded">
                <p className="ant-upload-text text-gray-500">{t(reasonKey)}</p>
              </div>
            );
          }
          return (
            <Dragger
              accept={AIDP_ACCEPT_STRING}
              multiple
              showUploadList={false}
              beforeUpload={(_file) => {
                // Queue the file and defer validation + upload until the
                // synchronous batch of beforeUpload calls finishes. Each batch
                // flushes in a single frame so toasts and handleUpload run once.
                pendingFilesRef.current.push(_file);
                if (rafIdRef.current === null) {
                  rafIdRef.current = requestAnimationFrame(() => {
                    const batch = pendingFilesRef.current;
                    pendingFilesRef.current = [];
                    rafIdRef.current = null;

                    const { valid } = partitionAidpFiles(batch, t, message);
                    if (valid.length > 0) {
                      handleUpload(valid);
                    }
                  });
                }
                return false;
              }}
              disabled={uploading}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">
                {uploading
                  ? t("aidpKnowledge.uploading")
                  : t("aidpKnowledge.uploadHint")}
              </p>
              <div className="ant-upload-hint mt-2 w-full min-w-0 max-w-full space-y-1 overflow-hidden px-4 whitespace-normal">
                <div>{t("aidpKnowledge.uploadHintCount")}</div>
                <div>{t("aidpKnowledge.uploadHintSize")}</div>
                <div className="w-full min-w-0 break-all leading-5 whitespace-normal">
                  {t("aidpKnowledge.uploadHintFormats")}
                </div>
              </div>
            </Dragger>
          );
        })()}
      </div>
    </div>
  );
};

export default AidpDocumentList;
