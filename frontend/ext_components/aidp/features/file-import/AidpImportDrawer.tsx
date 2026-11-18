// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { App, Button, Drawer, Input, Tooltip } from "antd";
import {
  DeleteOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  UploadOutlined,
} from "@ant-design/icons";

import { AIDP_ACCEPT_STRING } from "@/ext_components/aidp/features/file-import/uploadConstants";
import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";
import {
  AIDP_UPLOAD_CAPABILITIES,
  aidpUploadTransport,
} from "@/ext_components/aidp/shared/services/aidpUploadCenterAdapter";
import {
  collectDroppedFiles,
  filesFromPicker,
  type AidpDroppedFile,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpDropFiles";
import { normalizeFolderPath } from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFolderUtils";
import { useUploadCenter } from "@/hooks/upload/useUploadCenter";
import AidpFolderPickerModal from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderPickerModal";

import styles from "@/ext_components/aidp/features/file-import/AidpImportDrawer.module.css";

interface AidpImportDrawerProps {
  open: boolean;
  title: string;
  knowledgeBase: AidpKnowledgeBaseItem;
  /** Destination preselected when the drawer opens. */
  defaultFolderPath?: string;
  /** Files dropped on a tree node, staged before the user confirms. */
  initialFiles?: AidpDroppedFile[];
  onClose: () => void;
  /** Called after all queued files reach a terminal state. */
  onUploadComplete?: () => void;
}

const formatBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}K`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)}M`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)}G`;
};

const SelectionRow: React.FC<{
  row: AidpDroppedFile;
  onRemove: (row: AidpDroppedFile) => void;
}> = ({ row, onRemove }) => {
  const { t } = useTranslation();
  return (
    <div className={`${styles.fileRow} ${styles.dashedRow}`}>
      <div className={styles.fileIcon} aria-hidden="true">
        <FileTextOutlined />
      </div>
      <div className={styles.fileText}>
        <Tooltip title={row.relativePath}>
          <div className={styles.fileName}>{row.relativePath}</div>
        </Tooltip>
        <Tooltip
          title={`${formatBytes(row.file.size)} · ${t("uploadCenter.statusQueued")}`}
        >
          <div className={styles.fileDetail}>
            {formatBytes(row.file.size)} · {t("uploadCenter.statusQueued")}
          </div>
        </Tooltip>
      </div>
      <Button
        className={styles.deleteButton}
        type="text"
        icon={<DeleteOutlined />}
        aria-label={`${t("common.delete")} ${row.relativePath}`}
        onClick={() => onRemove(row)}
      />
    </div>
  );
};

const AidpImportDrawer: React.FC<AidpImportDrawerProps> = ({
  open,
  title,
  knowledgeBase,
  defaultFolderPath = "/",
  initialFiles,
  onClose,
  onUploadComplete,
}) => {
  const { t, i18n } = useTranslation();
  const { message } = App.useApp();
  const { enqueue } = useUploadCenter();
  const [rows, setRows] = useState<AidpDroppedFile[]>([]);
  const [targetFolder, setTargetFolder] = useState("/");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const rowsRef = useRef<AidpDroppedFile[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  const replaceRows = useCallback((next: AidpDroppedFile[]) => {
    rowsRef.current = next;
    setRows(next);
  }, []);

  useEffect(() => {
    folderInputRef.current?.setAttribute("webkitdirectory", "");
    folderInputRef.current?.setAttribute("directory", "");
  }, []);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- Opening/closing the drawer must start from the caller's staged files and folder. */
    if (!open) {
      replaceRows([]);
      return;
    }
    setTargetFolder(normalizeFolderPath(defaultFolderPath));
    replaceRows(initialFiles ?? []);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [defaultFolderPath, initialFiles, open, replaceRows]);

  const addFiles = useCallback(
    (incoming: AidpDroppedFile[]) => {
      if (incoming.length === 0) return;
      const current = rowsRef.current;
      const seen = new Set(
        current.map(
          (row) =>
            `${row.relativePath}|${row.file.name}|${row.file.size}|${row.file.lastModified}`
        )
      );
      const next = [...current];
      let duplicateCount = 0;
      let limitCount = 0;
      let currentBytes = current.reduce((sum, row) => sum + row.file.size, 0);
      for (const row of incoming) {
        const key = `${row.relativePath}|${row.file.name}|${row.file.size}|${row.file.lastModified}`;
        if (seen.has(key)) {
          duplicateCount += 1;
          continue;
        }
        if (
          next.length >= AIDP_UPLOAD_CAPABILITIES.maxFilesTotal ||
          currentBytes + row.file.size > AIDP_UPLOAD_CAPABILITIES.maxBytesTotal
        ) {
          limitCount += 1;
          continue;
        }
        seen.add(key);
        next.push(row);
        currentBytes += row.file.size;
      }
      if (limitCount > 0) {
        message.error(
          t("uploadCenter.selectionLimit", {
            maxFiles: AIDP_UPLOAD_CAPABILITIES.maxFilesTotal,
            maxSize: Math.round(
              AIDP_UPLOAD_CAPABILITIES.maxBytesTotal / (1024 * 1024 * 1024)
            ),
          })
        );
      } else if (duplicateCount > 0) {
        message.warning(
          t("uploadCenter.duplicateSelection", { count: duplicateCount })
        );
      }
      replaceRows(next);
    },
    [message, replaceRows, t]
  );

  const handleFileInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    addFiles(filesFromPicker(event.target.files ?? []));
    event.target.value = "";
  };

  const handleClose = useCallback(() => {
    replaceRows([]);
    onClose();
  }, [onClose, replaceRows]);

  const handleImport = useCallback(() => {
    if (rowsRef.current.length === 0) return;
    const folder = normalizeFolderPath(targetFolder);
    enqueue({
      files: rowsRef.current.map((row) => ({
        file: row.file,
        relativePath: row.relativePath,
      })),
      context: {
        knowledgeBaseId: knowledgeBase.kds_id,
        knowledgeBaseName: knowledgeBase.kds_name,
        targetFolder: folder,
        language: i18n.language,
        translate: t,
      },
      transport: aidpUploadTransport,
      sourceLabel:
        rowsRef.current.length === 1
          ? rowsRef.current[0].relativePath
          : t("uploadCenter.fileCountLabel", {
              count: rowsRef.current.length,
            }),
      onComplete: onUploadComplete,
    });
    replaceRows([]);
    onClose();
  }, [
    enqueue,
    i18n.language,
    knowledgeBase.kds_id,
    knowledgeBase.kds_name,
    onClose,
    onUploadComplete,
    replaceRows,
    t,
    targetFolder,
  ]);

  const removeRow = useCallback(
    (row: AidpDroppedFile) => {
      replaceRows(
        rowsRef.current.filter(
          (item) =>
            !(item.relativePath === row.relativePath && item.file === row.file)
        )
      );
    },
    [replaceRows]
  );

  return (
    <>
      <Drawer
        className={styles.drawer}
        title={title}
        placement="right"
        size={764}
        open={open}
        onClose={handleClose}
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
              <Button autoInsertSpace={false} onClick={handleClose}>
                {t("common.cancel")}
              </Button>
              <Button
                autoInsertSpace={false}
                type="primary"
                disabled={rows.length === 0}
                onClick={handleImport}
              >
                {t("aidpKnowledge.importAction")}
              </Button>
            </div>
          </div>
        }
      >
        <div className={styles.drawerBody}>
          <div className={styles.targetSection}>
            <label className={styles.targetLabel} htmlFor="aidp-target-folder">
              <span className={styles.required}>*</span>
              {t("aidpKnowledge.uploadTargetLabel")}
            </label>
            <div className={styles.targetRow}>
              <Input
                id="aidp-target-folder"
                value={targetFolder}
                onChange={(event) => setTargetFolder(event.target.value)}
                onBlur={() =>
                  setTargetFolder((current) => normalizeFolderPath(current))
                }
                placeholder="/"
              />
              <Button
                autoInsertSpace={false}
                icon={<FolderOpenOutlined />}
                onClick={() => setPickerOpen(true)}
              >
                {t("aidpKnowledge.browseFolder")}
              </Button>
            </div>
            <div className={styles.targetHint}>
              {t("aidpKnowledge.uploadTargetHint")}
            </div>
          </div>

          <div
            className={`${styles.dropzone} ${dragOver ? styles.dropzoneActive : ""}`}
            role="button"
            tabIndex={0}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragOver(false);
              void collectDroppedFiles(event.dataTransfer).then(addFiles);
            }}
          >
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
            <div className={styles.pickerActions}>
              <Button
                autoInsertSpace={false}
                size="small"
                onClick={(event) => {
                  event.stopPropagation();
                  fileInputRef.current?.click();
                }}
              >
                {t("aidpKnowledge.selectFiles")}
              </Button>
              <Button
                autoInsertSpace={false}
                size="small"
                onClick={(event) => {
                  event.stopPropagation();
                  folderInputRef.current?.click();
                }}
              >
                {t("aidpKnowledge.selectFolder")}
              </Button>
            </div>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            accept={AIDP_ACCEPT_STRING}
            onChange={handleFileInput}
          />
          <input
            ref={folderInputRef}
            type="file"
            multiple
            hidden
            onChange={handleFileInput}
          />

          <div className={styles.fileList} aria-live="polite">
            {rows.length === 0 ? (
              <div className={styles.emptyState}>
                {t("aidpKnowledge.importEmpty")}
              </div>
            ) : (
              rows.map((row) => (
                <SelectionRow
                  key={`${row.relativePath}|${row.file.name}|${row.file.size}|${row.file.lastModified}`}
                  row={row}
                  onRemove={removeRow}
                />
              ))
            )}
          </div>
          <div className={styles.fileCount}>
            {t("uploadCenter.selectedCount", { count: rows.length })}
          </div>
        </div>
      </Drawer>

      <AidpFolderPickerModal
        open={pickerOpen}
        knowledgeBaseId={knowledgeBase.kds_id}
        rootLabel={knowledgeBase.kds_name}
        title={t("aidpKnowledge.uploadTargetPickerTitle")}
        initialPath={targetFolder}
        onCancel={() => setPickerOpen(false)}
        onSelect={(path) => {
          setTargetFolder(path);
          setPickerOpen(false);
        }}
      />
    </>
  );
};

export default AidpImportDrawer;
