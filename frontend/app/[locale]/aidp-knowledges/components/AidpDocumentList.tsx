import React, { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";

import { Button, Upload, message, Tooltip } from "antd";
import { UploadOutlined, InboxOutlined, ReloadOutlined } from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import type { AidpDocumentItem } from "@/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/services/aidpKnowledgeService";

const { Dragger } = Upload;

interface AidpDocumentListProps {
  activeKb: AidpKnowledgeBaseItem | null;
  documents: AidpDocumentItem[];
  totalDocs: number;
  isLoading: boolean;
  serverUrl: string;
  apiKey: string;
  onDocsUploaded: () => void;
  onRefresh: () => void;
}

const AidpDocumentList: React.FC<AidpDocumentListProps> = ({
  activeKb,
  documents,
  totalDocs,
  isLoading,
  serverUrl,
  apiKey,
  onDocsUploaded,
  onRefresh,
}) => {
  const { t } = useTranslation();
  const [uploading, setUploading] = useState(false);

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
    <div className="w-full h-full bg-white border border-gray-200 rounded-md flex flex-col overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-gray-200 shrink-0">
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

      {/* Document table — compact; scrolls internally when content overflows. */}
      <div className="shrink-0 overflow-auto max-h-[50%] p-2 border-b border-gray-200">
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

      {/* Upload area — placed directly beneath the table, not stretched to the bottom. */}
      <div className="shrink-0 p-3">
        <Dragger
          multiple
          showUploadList={false}
          beforeUpload={(file, fileList) => {
            // Collect all files from this upload batch
            const allFiles = fileList
              .map((f) => f as unknown as File)
              .filter(Boolean);

            // Defer to avoid blocking antd
            setTimeout(() => handleUpload(allFiles), 0);
            return false; // Prevent default upload
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

      {/* Spacer absorbs any remaining column space so the Dragger sits just below content. */}
      <div className="flex-1 min-h-0" />
    </div>
  );
};

export default AidpDocumentList;
