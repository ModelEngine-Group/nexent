import React, { useState, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";

import { Button, Pagination, Upload, message, Tooltip } from "antd";
import { UploadOutlined, InboxOutlined, ReloadOutlined } from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import type { AidpDocumentItem } from "@/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/services/aidpKnowledgeService";

const { Dragger } = Upload;

interface AidpDocumentListProps {
  activeKb: AidpKnowledgeBaseItem | null;
  documents: AidpDocumentItem[];
  totalDocs: number;
  hasMore: boolean;
  isLoading: boolean;
  serverUrl: string;
  apiKey: string;
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
  hasMore,
  isLoading,
  serverUrl,
  apiKey,
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
          serverUrl,
          apiKey,
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
    [activeKb, serverUrl, apiKey, onDocsUploaded, t]
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
          When Count API is unavailable total may be unreliable, so we use
          has_more (derived from page fullness on the backend) as a fallback
          signal. To make Pagination show at least "one more page" we inflate
          total to be just beyond the current page when has_more is true but
          total ≤ currentPage*pageSize. */}
      {documents.length > 0 && (() => {
        const effectiveTotal = hasMore && totalDocs <= currentPage * pageSize
          ? currentPage * pageSize + pageSize + 1
          : totalDocs;
        return (
          <div className="px-4 py-2 border-b border-gray-200 flex justify-center">
            <Pagination
              current={currentPage}
              pageSize={pageSize}
              total={effectiveTotal}
              onChange={onPageChange}
              showSizeChanger={false}
              showTotal={(total) =>
                t("aidpKnowledge.showTotal", { count: total })
              }
              size="small"
            />
          </div>
        );
      })()}

      {/* Upload area */}
      <div className="p-3">
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
          disabled={uploading || !activeKb}
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
      </div>
    </div>
  );
};

export default AidpDocumentList;
