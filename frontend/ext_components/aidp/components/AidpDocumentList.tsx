import React, { useState, useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { Button, Modal, Pagination, Upload, message, Tooltip } from "antd";
import { InboxOutlined, ReloadOutlined } from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import type { AidpDocumentItem } from "@/ext_components/aidp/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { AIDP_ACCEPT_STRING } from "@/const/knowledgeBase";
import log from "@/lib/logger";
import { partitionAidpFiles } from "@/services/uploadService";

const { Dragger } = Upload;

const resolveDownloadFilename = (response: Response, fallback: string) => {
  const contentDisposition = response.headers.get("content-disposition") || "";
  const encodedName = /filename\*=UTF-8''([^;]+)/i.exec(
    contentDisposition
  )?.[1];
  if (encodedName) {
    try {
      return decodeURIComponent(encodedName);
    } catch {
      // Use the regular filename or document name when decoding fails.
    }
  }
  const plainName = /filename="?([^";]+)"?/i.exec(contentDisposition)?.[1];
  return plainName || response.headers.get("x-file-name") || fallback;
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
  onDocsUploaded: () => void;
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
  const [selectedFileUuids, setSelectedFileUuids] = useState<string[]>([]);
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

  useEffect(() => {
    setSelectedFileUuids([]);
  }, [activeKb?.kds_id, documents]);

  const selectableDocuments = documents.filter((doc) =>
    Boolean(doc.file_uuid && doc.file_ino_no)
  );
  const allDocumentsSelected =
    selectableDocuments.length > 0 &&
    selectableDocuments.every((doc) =>
      selectedFileUuids.includes(doc.file_uuid)
    );

  const toggleDocumentSelection = useCallback((fileUuid: string) => {
    setSelectedFileUuids((current) =>
      current.includes(fileUuid)
        ? current.filter((uuid) => uuid !== fileUuid)
        : [...current, fileUuid]
    );
  }, []);

  const toggleAllDocuments = useCallback(() => {
    setSelectedFileUuids(
      allDocumentsSelected
        ? []
        : selectableDocuments.map((document) => document.file_uuid)
    );
  }, [allDocumentsSelected, selectableDocuments]);

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
    (documentsToDelete: AidpDocumentItem[]) => {
      if (!activeKb || documentsToDelete.length === 0) return;
      Modal.confirm({
        title: t("aidpKnowledge.confirmDeleteDocsTitle"),
        content: t("aidpKnowledge.confirmDeleteDocsContent", {
          count: documentsToDelete.length,
        }),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        okButtonProps: { danger: true },
        centered: true,
        onOk: async () => {
          setDeleting(true);
          try {
            const result = await aidpKnowledgeService.removeDocs(
              activeKb.kds_id,
              documentsToDelete.map(({ file_uuid, file_ino_no }) => ({
                file_uuid,
                file_ino_no,
              }))
            );
            if (result.summary.failed === 0) {
              message.success(
                t("aidpKnowledge.deleteDocsSuccess", {
                  count: result.summary.success,
                })
              );
            } else if (result.summary.success > 0) {
              message.warning(
                t("aidpKnowledge.deleteDocsPartial", {
                  success: result.summary.success,
                  failed: result.summary.failed,
                })
              );
            } else {
              message.error(t("aidpKnowledge.deleteDocsFailed"));
            }
            if (result.summary.success > 0) {
              onDocsUploaded();
            }
            setSelectedFileUuids([]);
          } catch (error) {
            log.error("Failed to delete AIDP documents:", error);
            message.error(t("aidpKnowledge.deleteDocsFailed"));
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
      if (!activeKb) return;
      if (fileList.length === 0) return;

      setUploading(true);
      try {
        const result = await aidpKnowledgeService.uploadDocs(
          activeKb.kds_id,
          fileList
        );

        const failureDetails = result.failed_list.map((item) => {
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
          onDocsUploaded();
        } else {
          message.success(
            t("aidpKnowledge.uploadSuccess", { count: result.summary.success })
          );
          onDocsUploaded();
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
            <h3 className="text-base font-semibold text-blue-500 truncate">
              {activeKb?.kds_name || ""}
            </h3>
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
        {canDeleteDocuments && (
          <div className="mt-3 flex items-center gap-3">
            <Button
              danger
              size="small"
              loading={deleting}
              disabled={selectedFileUuids.length === 0}
              onClick={() =>
                handleDelete(
                  documents.filter((doc) =>
                    selectedFileUuids.includes(doc.file_uuid)
                  )
                )
              }
            >
              {t("aidpKnowledge.deleteSelected", {
                count: selectedFileUuids.length,
              })}
            </Button>
          </div>
        )}
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
                  <th className="w-10 px-4 py-2 text-left">
                    <input
                      type="checkbox"
                      aria-label={t("aidpKnowledge.selectAllDocuments")}
                      checked={allDocumentsSelected}
                      disabled={
                        !canDeleteDocuments || selectableDocuments.length === 0
                      }
                      onChange={toggleAllDocuments}
                    />
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docFileName")}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docType")}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docSize")}
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docCreatedAt")}
                  </th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">
                    {t("aidpKnowledge.docActions")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {documents.map((doc) => (
                  <tr
                    key={doc.file_uuid || doc.file_ino_no}
                    className="hover:bg-gray-50"
                  >
                    <td className="w-10 px-4 py-2">
                      <input
                        type="checkbox"
                        aria-label={t("aidpKnowledge.selectDocument", {
                          name: doc.file_name,
                        })}
                        checked={selectedFileUuids.includes(doc.file_uuid)}
                        disabled={!canDeleteDocuments || !doc.file_uuid}
                        onChange={() => toggleDocumentSelection(doc.file_uuid)}
                      />
                    </td>
                    <td className="px-4 py-2">
                      <div
                        className="text-sm font-medium text-gray-800 truncate max-w-[250px]"
                        title={doc.file_name}
                      >
                        {doc.file_name}
                      </div>
                      <div className="text-xs text-gray-400">
                        {doc.file_ino_no}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-600">
                      {doc.file_type || "-"}
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-600">
                      {formatSize(doc.file_size)}
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-600">
                      {doc.created_at
                        ? new Date(doc.created_at).toLocaleString()
                        : "-"}
                    </td>
                    <td className="px-4 py-2 text-right">
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
                            onClick={() => handleDelete([doc])}
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
