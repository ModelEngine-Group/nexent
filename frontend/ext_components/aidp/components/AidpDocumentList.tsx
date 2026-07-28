import React, { useState, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";

import { Button, Pagination, Upload, message, Tooltip } from "antd";
import { UploadOutlined, InboxOutlined, ReloadOutlined } from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import type { AidpDocumentItem } from "@/ext_components/aidp/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";

const { Dragger } = Upload;

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
  const { t } = useTranslation();
  const [uploading, setUploading] = useState(false);
  // Antd Dragger fires beforeUpload once per file in a multi-select batch,
  // each time passing the SAME fileList ref. Use it as a dedup key so we
  // only kick off one upload per user action.
  const batchRef = useRef<unknown>(null);

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

        if (result.failed > 0 && result.success === 0) {
          message.error(t("aidpKnowledge.uploadFailed"));
        } else if (result.failed > 0) {
          message.warning(
            t("aidpKnowledge.uploadPartial", {
              success: result.success,
              failed: result.failed,
            })
          );
          onDocsUploaded();
        } else {
          message.success(
            t("aidpKnowledge.uploadSuccess", { count: result.success })
          );
          onDocsUploaded();
        }
      } catch (error) {
        message.error(t("aidpKnowledge.uploadFailed"));
      } finally {
        setUploading(false);
      }
    },
    [activeKb, onDocsUploaded, t]
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
                    <td className="px-4 py-2">
                      <div className="text-sm font-medium text-gray-800 truncate max-w-[250px]" title={doc.file_name}>
                        {doc.file_name}
                      </div>
                      <div className="text-xs text-gray-400">{doc.file_ino_no}</div>
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
      {documents.length > 0 && (() => {
        // When total is unreliable we still need antd to know when to
        // enable "next": set total just past the current page if there is
        // a next page, otherwise clamp to the current page end.
        const effectiveTotal = totalReliable
          ? totalDocs
          : (hasMore
              ? currentPage * pageSize + 1
              : currentPage * pageSize);
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
            !!activeKb &&
            !isUnavailable &&
            activeKb.permission === "EDIT";
          if (!canUpload) {
            const reasonKey = !activeKb
              ? "aidpKnowledge.uploadNoKb"
              : isUnavailable
              ? "aidpKnowledge.uploadKbUnavailable"
              : "aidpKnowledge.uploadReadOnly";
            return (
              <div className="ant-upload ant-upload-drag p-6 text-center border border-dashed border-gray-200 rounded">
                <p className="ant-upload-text text-gray-500">
                  {t(reasonKey)}
                </p>
              </div>
            );
          }
          return (
            <Dragger
              multiple
              showUploadList={false}
              beforeUpload={(_file, fileList) => {
                // Dedupe: antd calls beforeUpload N times for N selected files,
                // passing the same `fileList` reference each time. Only process
                // the FIRST invocation per batch to prevent duplicate uploads.
                if (batchRef.current === fileList) return false;
                batchRef.current = fileList;

                const allFiles = fileList
                  .map((f) => f as unknown as File)
                  .filter(Boolean);

                // Defer to avoid blocking antd
                setTimeout(() => {
                  handleUpload(allFiles);
                  batchRef.current = null;
                }, 0);
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
              <p className="ant-upload-hint">
                {t("aidpKnowledge.uploadHintDetail")}
              </p>
            </Dragger>
          );
        })()}
      </div>
    </div>
  );
};

export default AidpDocumentList;
