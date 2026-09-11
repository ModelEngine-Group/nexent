import React, { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Pagination, Upload, message, Tooltip } from "antd";
import {
  FileTextOutlined,
  InboxOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import type { AidpDocumentItem } from "@/ext_components/aidp/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { AIDP_ACCEPT_STRING } from "@/const/knowledgeBase";
import { partitionAidpFiles } from "@/services/uploadService";

const { Dragger } = Upload;

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
  const pendingFilesRef = useRef<File[]>([]);
  const rafIdRef = useRef<number | null>(null);

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

  const isUnavailable =
    activeKb?.resource_status === "UNAVAILABLE" ||
    activeKb?.resource_status === "ORPHANED";
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
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div className="flex shrink-0 items-start justify-between gap-4 border-b border-gray-100 px-6 pb-5 pt-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
            <FileTextOutlined />
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-xl font-semibold tracking-tight text-blue-600">
              {activeKb?.kds_name || ""}
            </h2>
            <span className="mt-1 block text-sm text-gray-500">
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
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                    {t("aidpKnowledge.docSize")}
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                    {t("aidpKnowledge.docCreatedAt")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {documents.map((doc) => (
                  <tr
                    key={doc.file_ino_no}
                    className="transition-colors hover:bg-gray-50"
                  >
                    <td className="max-w-[280px] px-4 py-3">
                      <div
                        className="truncate text-sm font-medium text-gray-800"
                        title={doc.file_name}
                      >
                        {doc.file_name}
                      </div>
                      <div
                        className="mt-1 truncate text-xs text-gray-400"
                        title={doc.file_ino_no}
                      >
                        {doc.file_ino_no}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {doc.file_type || "-"}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {formatSize(doc.file_size)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
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
