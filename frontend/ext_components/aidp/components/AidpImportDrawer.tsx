import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { App, Button, Drawer, Tooltip, Upload } from "antd";
import type { UploadProps } from "antd";
import {
  DeleteOutlined,
  FileTextOutlined,
  UploadOutlined,
} from "@ant-design/icons";

import {
  AIDP_ACCEPT_STRING,
  AIDP_MAX_UPLOAD_FILE_COUNT,
} from "@/ext_components/aidp/const/upload";
import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/types/knowledge";
import type { AidpUploadFailedItem } from "@/ext_components/aidp/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { validateAidpFiles } from "@/ext_components/aidp/utils/uploadValidation";
import { ApiError } from "@/services/api";
import { getAidpUploadErrorMessage } from "../services/aidpUploadUtils";

import styles from "./AidpImportDrawer.module.css";

const { Dragger } = Upload;

type ImportFileStatus = "pending" | "uploading" | "failed" | "success";

interface ImportFileRow {
  id: number;
  file: File;
  status: ImportFileStatus;
  progress: number;
  error?: string;
}

interface AidpImportDrawerProps {
  open: boolean;
  title: string;
  knowledgeBase: AidpKnowledgeBaseItem;
  onClose: () => void;
  onDocsUploaded: (uploadedFileIds: string[]) => void;
  onRefresh: () => void;
}

const formatBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}K`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)}M`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)}G`;
};

const getFailureReason = (
  item: AidpUploadFailedItem | undefined,
  language: string,
  translate: (key: string, options: { defaultValue: string }) => string,
  fallback: string
): string => {
  if (!item) return fallback;
  const reason = language.startsWith("zh")
    ? item.reason_zh || item.reason_en || fallback
    : item.reason_en || item.reason_zh || fallback;
  return item.code !== undefined && item.code !== ""
    ? getAidpUploadErrorMessage(
        new ApiError(item.code, reason),
        translate,
        fallback
      )
    : reason;
};

const ProgressRing: React.FC<{ percent: number }> = ({ percent }) => {
  const circumference = 2 * Math.PI * 6.5;
  const offset = circumference * (1 - percent / 100);
  return (
    <svg
      aria-label={`${percent}%`}
      className={styles.progressRing}
      width="18"
      height="18"
      viewBox="0 0 18 18"
    >
      <circle
        cx="9"
        cy="9"
        r="6.5"
        fill="none"
        stroke="white"
        strokeOpacity="0.5"
        strokeWidth="3"
      />
      <circle
        cx="9"
        cy="9"
        r="6.5"
        fill="none"
        stroke="#191919"
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 9 9)"
      />
    </svg>
  );
};

const AidpImportDrawer: React.FC<AidpImportDrawerProps> = ({
  open,
  title,
  knowledgeBase,
  onClose,
  onDocsUploaded,
  onRefresh,
}) => {
  const { t, i18n } = useTranslation();
  const { message } = App.useApp();
  const [rows, setRows] = useState<ImportFileRow[]>([]);
  const [uploading, setUploading] = useState(false);
  const rowsRef = useRef<ImportFileRow[]>([]);
  const uploadingRef = useRef(false);
  const mountedRef = useRef(true);
  const nextIdRef = useRef(0);
  const pendingSelectionRef = useRef<File[]>([]);
  const selectionFrameRef = useRef<number | null>(null);
  const abortControllersRef = useRef(new Map<number, AbortController>());

  const replaceRows = useCallback(
    (
      nextRows:
        ImportFileRow[] | ((current: ImportFileRow[]) => ImportFileRow[])
    ) => {
      const resolved =
        typeof nextRows === "function" ? nextRows(rowsRef.current) : nextRows;
      rowsRef.current = resolved;
      setRows(resolved);
    },
    []
  );

  useEffect(() => {
    mountedRef.current = true;
    const controllers = abortControllersRef.current;
    return () => {
      mountedRef.current = false;
      if (selectionFrameRef.current !== null) {
        window.cancelAnimationFrame(selectionFrameRef.current);
      }
      controllers.forEach((controller) => controller.abort());
    };
  }, []);

  const removeFile = useCallback(
    (row: ImportFileRow) => {
      if (row.status !== "failed") return;
      replaceRows((current) => current.filter((item) => item.id !== row.id));
    },
    [replaceRows]
  );

  const uploadPendingFiles = useCallback(async () => {
    const pendingRows = rowsRef.current.filter(
      (row) => row.status === "pending"
    );
    if (uploadingRef.current) return;
    if (pendingRows.length === 0) {
      setUploading(false);
      return;
    }

    uploadingRef.current = true;
    setUploading(true);
    const batchIds = new Set(pendingRows.map((row) => row.id));
    const controller = new AbortController();
    const batchId = pendingRows[0].id;
    abortControllersRef.current.set(batchId, controller);
    const updateBatch = (update: (row: ImportFileRow) => ImportFileRow) =>
      replaceRows((current) =>
        current.map((row) => (batchIds.has(row.id) ? update(row) : row))
      );
    updateBatch((row) => ({ ...row, status: "uploading", progress: 0 }));

    const uploadedFileIds: string[] = [];
    try {
      const result = await aidpKnowledgeService.uploadDocsWithProgress(
        knowledgeBase.kds_id,
        pendingRows.map((row) => row.file),
        (loaded, total) => {
          if (!mountedRef.current) return;
          // The batch percentage is intentionally shared by all uploading rows.
          const ratio =
            total > 0 ? Math.min(1, Math.max(0, loaded / total)) : 0;
          updateBatch((row) => ({
            ...row,
            progress: Math.round(ratio * 1000) / 10,
          }));
        },
        controller.signal
      );
      if (!mountedRef.current) return;
      const successes = [...result.success_list];
      const failures = [...result.failed_list];
      updateBatch((row) => {
        const successIndex = successes.findIndex(
          (item) => item.file_name === row.file.name
        );
        if (successIndex >= 0) {
          const [success] = successes.splice(successIndex, 1);
          if (success.file_ino_no)
            uploadedFileIds.push(String(success.file_ino_no));
          return { ...row, status: "success", progress: 100 };
        }
        const failureIndex = failures.findIndex(
          (item) => item.file_name === row.file.name
        );
        const failure =
          failureIndex >= 0 ? failures.splice(failureIndex, 1)[0] : undefined;
        return {
          ...row,
          status: "failed",
          error: getFailureReason(
            failure,
            i18n.language,
            t,
            t("aidpKnowledge.uploadFailed")
          ),
        };
      });
    } catch (error) {
      if (mountedRef.current && !controller.signal.aborted) {
        updateBatch((row) => ({
          ...row,
          status: "failed",
          error: getAidpUploadErrorMessage(
            error,
            t,
            t("aidpKnowledge.uploadFailed")
          ),
        }));
      }
    } finally {
      abortControllersRef.current.delete(batchId);
    }
    if (!mountedRef.current) return;
    uploadingRef.current = false;
    setUploading(false);
    onRefresh();

    const finishedRows = rowsRef.current.filter((row) => batchIds.has(row.id));
    const failedCount = finishedRows.filter(
      (row) => row.status === "failed"
    ).length;
    const succeededCount = finishedRows.filter(
      (row) => row.status === "success"
    ).length;
    if (uploadedFileIds.length > 0) onDocsUploaded(uploadedFileIds);

    if (failedCount > 0) {
      if (succeededCount > 0) {
        message.warning(
          t("aidpKnowledge.uploadPartial", {
            success: succeededCount,
            failed: failedCount,
          })
        );
      }
      return;
    }

    if (succeededCount > 0) {
      message.success(
        t("aidpKnowledge.uploadSuccess", { count: succeededCount })
      );
    }
  }, [
    i18n.language,
    knowledgeBase.kds_id,
    message,
    onDocsUploaded,
    onRefresh,
    replaceRows,
    t,
  ]);

  const flushSelection = useCallback(() => {
    const selectedFiles = pendingSelectionRef.current;
    pendingSelectionRef.current = [];
    selectionFrameRef.current = null;
    if (selectedFiles.length === 0) {
      setUploading(false);
      return;
    }

    const nextRows = [...rowsRef.current];
    const knownFiles = new Set(
      nextRows.map(
        ({ file }) => `${file.name}\u0000${file.size}\u0000${file.lastModified}`
      )
    );
    let duplicateCount = 0;
    let overLimitCount = 0;

    for (const file of selectedFiles) {
      const key = `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
      if (knownFiles.has(key)) {
        duplicateCount += 1;
        continue;
      }
      if (nextRows.length >= AIDP_MAX_UPLOAD_FILE_COUNT) {
        overLimitCount += 1;
        continue;
      }

      knownFiles.add(key);
      const validation = validateAidpFiles([file]);
      let error: string | undefined;
      if (validation.invalidType.length > 0) {
        error = t("aidpKnowledge.invalidFileType", { count: 1 });
      } else if (validation.oversized.length > 0) {
        error = t("aidpKnowledge.fileTooLarge", {
          fileName: file.name,
          maxSize: validation.oversized[0].maxSizeMb,
        });
      }

      nextRows.push({
        id: nextIdRef.current++,
        file,
        status: error ? "failed" : "pending",
        progress: 0,
        error,
      });
    }

    replaceRows(nextRows);
    void uploadPendingFiles();
    if (duplicateCount > 0) {
      message.info(t("aidpKnowledge.importDuplicateSelection"));
    }
    if (overLimitCount > 0) {
      message.error(
        t("aidpKnowledge.tooManyFiles", {
          count: nextRows.length + overLimitCount,
          maxCount: AIDP_MAX_UPLOAD_FILE_COUNT,
        })
      );
    }
  }, [message, replaceRows, t, uploadPendingFiles]);

  const collectFiles: NonNullable<UploadProps["beforeUpload"]> = useCallback(
    (file) => {
      if (uploadingRef.current) return false;
      setUploading(true);
      pendingSelectionRef.current.push(file as File);
      if (selectionFrameRef.current === null) {
        selectionFrameRef.current =
          window.requestAnimationFrame(flushSelection);
      }
      return false;
    },
    [flushSelection]
  );

  const handleClose = useCallback(() => {
    if (uploadingRef.current || pendingSelectionRef.current.length > 0) return;
    if (selectionFrameRef.current !== null) {
      window.cancelAnimationFrame(selectionFrameRef.current);
      selectionFrameRef.current = null;
    }
    pendingSelectionRef.current = [];
    replaceRows([]);
    onClose();
  }, [onClose, replaceRows]);

  const renderFileRow = (row: ImportFileRow) => {
    const borderClass =
      row.status === "success" ? styles.successRow : styles.dashedRow;
    const detail =
      row.status === "uploading"
        ? formatBytes(row.file.size)
        : row.status === "failed"
          ? row.error || t("aidpKnowledge.uploadFailed")
          : row.status === "success"
            ? `${formatBytes(row.file.size)} · ${t("aidpKnowledge.importUploadComplete")}`
            : `${formatBytes(row.file.size)} · ${t("aidpKnowledge.importPending")}`;

    return (
      <div className={`${styles.fileRow} ${borderClass}`} key={row.id}>
        <Tooltip
          title={
            row.status === "uploading" && row.progress >= 100
              ? t("aidpKnowledge.importAwaitingResult")
              : undefined
          }
        >
          <div className={styles.fileIcon} aria-hidden="true">
            <FileTextOutlined />
            {row.status === "uploading" && (
              <ProgressRing percent={row.progress} />
            )}
          </div>
        </Tooltip>
        <div className={styles.fileText}>
          <Tooltip title={row.file.name}>
            <div className={styles.fileName}>{row.file.name}</div>
          </Tooltip>
          <Tooltip title={row.error || detail}>
            <div
              className={
                row.status === "failed"
                  ? `${styles.fileDetail} ${styles.fileError}`
                  : styles.fileDetail
              }
            >
              {detail}
            </div>
          </Tooltip>
        </div>
        {row.status === "failed" && (
          <Button
            className={styles.deleteButton}
            type="text"
            icon={<DeleteOutlined />}
            aria-label={`${t("aidpKnowledge.delete")} ${row.file.name}`}
            onClick={() => removeFile(row)}
          />
        )}
      </div>
    );
  };

  return (
    <Drawer
      className={styles.drawer}
      title={title}
      placement="right"
      size={764}
      open={open}
      onClose={handleClose}
      closable={!uploading}
      maskClosable={!uploading}
      keyboard={!uploading}
      destroyOnHidden
      styles={{
        body: {
          minHeight: 0,
          padding: 24,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        },
        footer: { padding: "16px 24px" },
      }}
      footer={
        <div className={styles.footer}>
          <div className={styles.footerActions}>
            <Button
              autoInsertSpace={false}
              onClick={handleClose}
              disabled={uploading}
            >
              {t("common.cancel")}
            </Button>
            <Button
              autoInsertSpace={false}
              type="primary"
              disabled={uploading}
              onClick={handleClose}
            >
              {t("common.confirm")}
            </Button>
          </div>
        </div>
      }
    >
      <div className={styles.drawerBody}>
        <Dragger
          className={styles.dropzone}
          accept={AIDP_ACCEPT_STRING}
          multiple
          showUploadList={false}
          beforeUpload={collectFiles}
          disabled={uploading || rows.length >= AIDP_MAX_UPLOAD_FILE_COUNT}
        >
          <div className={styles.dropzoneContent}>
            <UploadOutlined className={styles.dropzoneIcon} />
            <div className={styles.dropzoneTitle}>
              {t("aidpKnowledge.uploadHint")}
            </div>
            <div className={styles.dropzoneDescription}>
              {t("aidpKnowledge.importDescription")}
            </div>
            <div className={styles.dropzoneNotes}>
              <div>{t("aidpKnowledge.uploadHintCount")}</div>
              <div>{t("aidpKnowledge.uploadHintSize")}</div>
              <div className={styles.formats}>
                {t("aidpKnowledge.uploadHintFormats")}
              </div>
            </div>
          </div>
        </Dragger>
        <div className={styles.fileList} aria-live="polite">
          {rows.length === 0 ? (
            <div className={styles.emptyState}>
              {t("aidpKnowledge.importEmpty")}
            </div>
          ) : (
            rows.map(renderFileRow)
          )}
        </div>
        <div className={styles.fileCount}>
          {t("aidpKnowledge.importFileCount", {
            count: rows.length,
            maxCount: AIDP_MAX_UPLOAD_FILE_COUNT,
          })}
        </div>
      </div>
    </Drawer>
  );
};

export default AidpImportDrawer;
