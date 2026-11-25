// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Alert, App, Button, Dropdown, Input, Table, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { MenuProps } from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  FolderOutlined,
  MoreOutlined,
  ReloadOutlined,
  SearchOutlined,
  UploadOutlined,
} from "@ant-design/icons";

import type {
  AidpDocumentItem,
  AidpFolderFileItem,
  AidpKbDetail,
} from "@/ext_components/aidp/shared/types/management";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import {
  getAidpErrorMessage,
  isAidpNameConflictError,
} from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { getAidpDownloadFilename } from "@/ext_components/aidp/shared/utils/aidpDownloadFilename";
import { ApiError } from "@/services/api";
import log from "@/lib/logger";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import AidpImportDrawer from "@/ext_components/aidp/features/file-import/AidpImportDrawer";
import AidpResizableTitle from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import { FilePreviewDrawer } from "@/components/common/filePreviewDrawer";
import { useAidpFolderTree } from "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpFolderTree";
import { useAidpIngestedFileSearch } from "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpIngestedFileSearch";
import AidpFolderTree, {
  type AidpFolderNodeTarget,
} from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderTree";
import AidpFolderNameModal from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderNameModal";
import AidpFolderPickerModal from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderPickerModal";
import AidpFilesEmptyState from "@/ext_components/aidp/pages/knowledge-files/components/AidpFilesEmptyState";
import panelStyles from "@/ext_components/aidp/pages/knowledge-files/components/AidpKnowledgeFilesPanel.module.css";
import {
  AIDP_DETAIL_PAGE_SIZE,
  folderTreeStatusMeta,
  formatDetailDateTime,
  formatFileSize,
  splitFileNameExtension,
  sumColumnWidths,
  withResizableHeaders,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";
import {
  folderPathSegments,
  joinFolderPath,
  parentFolderPath,
  replaceFolderPrefix,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFolderUtils";
import type { AidpDroppedFile } from "@/ext_components/aidp/pages/knowledge-files/utils/aidpDropFiles";
import {
  hasAidpFileMoveDrag,
  readAidpFileMoveDrag,
  setAidpFileMoveDragImage,
  writeAidpFileMoveDrag,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFileDrag";

interface AidpKnowledgeFilesPanelProps {
  knowledgeBase: AidpKbDetail;
  canEdit: boolean;
  isAvailable: boolean;
  pollingPaused?: boolean;
  onFilesChanged?: () => void;
}

type FolderTableRow = {
  key: string;
  kind: "folder";
  name: string;
  path: string;
};

type FileTableRow = {
  key: string;
  kind: "file";
  name: string;
  file: AidpFolderFileItem;
};

type FileTableRecord = FolderTableRow | FileTableRow;

type FolderNameDialog =
  | { mode: "create"; parentPath: string }
  | { mode: "rename"; target: AidpFolderNodeTarget };

interface FileMoveRequest {
  fileUuids: string[];
  title: string;
}

interface FileMoveFailureItem {
  fileUuid: string;
  fileName: string;
  reason: string;
}

interface FileMoveFailure {
  successCount: number;
  failedCount: number;
  targetFolder: string;
  items: FileMoveFailureItem[];
}

const FILE_COLUMN_MIN_WIDTHS: Record<string, number> = {
  file_name: 140,
  file_type: 55,
  file_size: 60,
  created_at: 100,
  updated_at: 100,
  file_status: 80,
  actions: 105,
};

// AIDP caps a single batch document removal request at 10 files.
const AIDP_BATCH_DELETE_MAX = 10;

const toDocumentItem = (file: AidpFolderFileItem): AidpDocumentItem => ({
  file_uuid: file.file_uuid || "",
  file_ino_no: "",
  file_name: file.file_name || "",
  file_type: file.file_type,
  file_size: file.file_size,
  updated_at: file.updated_at || undefined,
  status: file.status,
});

const AidpKnowledgeFilesPanel: React.FC<AidpKnowledgeFilesPanelProps> = ({
  knowledgeBase,
  canEdit,
  isAvailable,
  pollingPaused = false,
  onFilesChanged,
}) => {
  const { t, i18n } = useTranslation();
  const { message, modal } = App.useApp();

  const [currentPath, setCurrentPath] = useState("/");
  // Top box = full-tree search; table header search = current folder.
  const [globalKeywordInput, setGlobalKeywordInput] = useState("");
  const [globalKeyword, setGlobalKeyword] = useState("");
  const [folderKeywordInput, setFolderKeywordInput] = useState("");
  const [folderKeyword, setFolderKeyword] = useState("");
  const [folderSearchOpen, setFolderSearchOpen] = useState(false);
  const [pageParams, setPageParams] = useState({
    page: 1,
    pageSize: AIDP_DETAIL_PAGE_SIZE,
  });
  const [searchPageParams, setSearchPageParams] = useState({
    page: 1,
    pageSize: AIDP_DETAIL_PAGE_SIZE,
  });
  const [selectedFileKeys, setSelectedFileKeys] = useState<React.Key[]>([]);
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({});
  const [treeReloadToken, setTreeReloadToken] = useState(0);
  const [importState, setImportState] = useState<{
    open: boolean;
    target: string;
    files: AidpDroppedFile[];
  }>({ open: false, target: "/", files: [] });
  const [folderNameDialog, setFolderNameDialog] =
    useState<FolderNameDialog | null>(null);
  const [folderNameSaving, setFolderNameSaving] = useState(false);
  const [folderMoveTarget, setFolderMoveTarget] =
    useState<AidpFolderNodeTarget | null>(null);
  const [fileMoveRequest, setFileMoveRequest] =
    useState<FileMoveRequest | null>(null);
  const [fileRenameTarget, setFileRenameTarget] =
    useState<AidpFolderFileItem | null>(null);
  const [fileRenameSaving, setFileRenameSaving] = useState(false);
  const [retryingFileUuid, setRetryingFileUuid] = useState<string | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [previewFile, setPreviewFile] = useState<AidpDocumentItem | null>(null);
  const [moveFailures, setMoveFailures] = useState<FileMoveFailure | null>(
    null
  );
  const [movingFileUuids, setMovingFileUuids] = useState<string[]>([]);
  const [dragOverFolderKey, setDragOverFolderKey] = useState<string | null>(
    null
  );
  const [breadcrumbDropPath, setBreadcrumbDropPath] = useState<string | null>(
    null
  );

  const dialogOpen =
    importState.open ||
    folderNameDialog !== null ||
    folderMoveTarget !== null ||
    fileMoveRequest !== null ||
    fileRenameTarget !== null ||
    deleteConfirmOpen ||
    previewFile !== null;

  const treeQuery = useAidpFolderTree(
    knowledgeBase.kds_id,
    currentPath,
    pageParams.page,
    pageParams.pageSize,
    folderKeyword,
    pollingPaused || dialogOpen
  );
  const folders = useMemo(
    () => treeQuery.data?.folders ?? [],
    [treeQuery.data]
  );
  const files = useMemo(
    () => treeQuery.data?.files.value ?? [],
    [treeQuery.data]
  );
  const fileTotal = treeQuery.data?.files.total ?? files.length;
  const loading = treeQuery.isFetching;
  const fileError = treeQuery.isError
    ? getAidpErrorMessage(
        treeQuery.error,
        t,
        t("aidpKnowledge.detailFilesLoadFailed")
      )
    : undefined;

  const globalSearchActive = globalKeyword.trim().length > 0;
  const searchQuery = useAidpIngestedFileSearch(
    knowledgeBase.kds_id,
    searchPageParams.page,
    searchPageParams.pageSize,
    globalKeyword,
    pollingPaused || dialogOpen
  );
  const searchFiles = useMemo(
    () => searchQuery.data?.value ?? [],
    [searchQuery.data]
  );
  const displayedFiles = globalSearchActive ? searchFiles : files;
  const displayedTotal = globalSearchActive
    ? (searchQuery.data?.total_count ?? searchFiles.length)
    : fileTotal;
  const displayedLoading = globalSearchActive
    ? searchQuery.isFetching
    : loading;
  const displayedError = globalSearchActive
    ? searchQuery.isError
      ? getAidpErrorMessage(
          searchQuery.error,
          t,
          t("aidpKnowledge.detailFilesLoadFailed")
        )
      : undefined
    : fileError;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = globalKeywordInput.trim();
      setGlobalKeyword((current) => (current === next ? current : next));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [globalKeywordInput]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = folderKeywordInput.trim();
      setFolderKeyword((current) => (current === next ? current : next));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [folderKeywordInput]);

  useEffect(() => {
    if (!globalKeyword.trim()) return;
    /* eslint-disable react-hooks/set-state-in-effect -- Full-tree search takes over the single search mode. */
    setFolderKeywordInput("");
    setFolderKeyword("");
    setFolderSearchOpen(false);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [globalKeyword]);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- Filter changes restart pagination and clear the previous page's selection. */
    setPageParams((current) =>
      current.page === 1 ? current : { ...current, page: 1 }
    );
    setSelectedFileKeys([]);
    setMoveFailures(null);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [currentPath, folderKeyword]);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- Full-tree filter changes restart its own pagination. */
    setSearchPageParams((current) =>
      current.page === 1 ? current : { ...current, page: 1 }
    );
    setSelectedFileKeys([]);
    setMoveFailures(null);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [globalKeyword]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- A new search page cannot keep keys from the previous page.
    setSelectedFileKeys([]);
    setMoveFailures(null);
  }, [searchPageParams.page, searchPageParams.pageSize]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- A new page cannot keep keys from the previous page.
    setSelectedFileKeys([]);
    setMoveFailures(null);
  }, [pageParams.page, pageParams.pageSize]);

  const refreshAll = useCallback(() => {
    setTreeReloadToken((current) => current + 1);
    void treeQuery.refetch();
    void searchQuery.refetch();
    onFilesChanged?.();
  }, [onFilesChanged, searchQuery, treeQuery]);

  const openFolder = useCallback((path: string) => {
    setCurrentPath(path);
    setGlobalKeyword("");
    setGlobalKeywordInput("");
    setFolderKeyword("");
    setFolderKeywordInput("");
    setFolderSearchOpen(false);
    setPageParams((current) => ({ ...current, page: 1 }));
    setSearchPageParams((current) => ({ ...current, page: 1 }));
    setSelectedFileKeys([]);
    setMoveFailures(null);
  }, []);

  const openImport = useCallback(
    (target: string, droppedFiles: AidpDroppedFile[] = []) => {
      setImportState({ open: true, target, files: droppedFiles });
    },
    []
  );

  const rows = useMemo<FileTableRecord[]>(() => {
    const folderRows: FolderTableRow[] =
      !globalSearchActive && pageParams.page === 1 && !folderKeyword.trim()
        ? folders.map((folder) => {
            const path = joinFolderPath(currentPath, folder.folder_name);
            return {
              key: `folder:${path}`,
              kind: "folder",
              name: folder.folder_name,
              path,
            };
          })
        : [];
    const fileRows: FileTableRow[] = displayedFiles.map((file, index) => ({
      key: `file:${file.file_uuid || `${index}:${file.file_name || ""}`}`,
      kind: "file",
      name: file.file_name || "",
      file,
    }));
    return [...folderRows, ...fileRows];
  }, [
    currentPath,
    displayedFiles,
    folders,
    folderKeyword,
    globalSearchActive,
    pageParams.page,
  ]);

  const selectedFileUuids = useMemo(() => {
    const selected = new Set(selectedFileKeys);
    return displayedFiles
      .filter(
        (file) =>
          selected.has(`file:${file.file_uuid || ""}`) &&
          Boolean(file.file_uuid)
      )
      .map((file) => file.file_uuid as string);
  }, [displayedFiles, selectedFileKeys]);

  const fileNameByUuid = useMemo(
    () =>
      new Map(
        displayedFiles
          .filter((file) => file.file_uuid)
          .map((file) => [file.file_uuid as string, file.file_name || ""])
      ),
    [displayedFiles]
  );

  const permissionsForFile = useCallback(
    (file: AidpFolderFileItem) =>
      folderTreeStatusMeta(file.status)?.permissions ?? null,
    []
  );

  const selectedFileItems = useMemo(
    () =>
      displayedFiles.filter(
        (file) =>
          file.file_uuid && selectedFileKeys.includes(`file:${file.file_uuid}`)
      ),
    [displayedFiles, selectedFileKeys]
  );

  const selectedDeletableUuids = useMemo(
    () =>
      selectedFileItems
        .filter((file) => permissionsForFile(file)?.canDelete)
        .map((file) => file.file_uuid as string),
    [permissionsForFile, selectedFileItems]
  );

  const selectedMovableUuids = useMemo(
    () =>
      selectedFileItems
        .filter((file) => permissionsForFile(file)?.canMove)
        .map((file) => file.file_uuid as string),
    [permissionsForFile, selectedFileItems]
  );

  const performFileMove = useCallback(
    async (fileUuids: string[], targetFolder: string) => {
      if (fileUuids.length === 0) return;
      if (targetFolder === currentPath) {
        message.info(t("aidpKnowledge.fileMoveSameFolder"));
        return;
      }
      setMoveFailures(null);
      setMovingFileUuids(fileUuids);
      try {
        const result = await aidpKnowledgeService.moveFiles(
          knowledgeBase.kds_id,
          fileUuids,
          targetFolder
        );
        const failedItems = (result.failed_list ?? []).map((item) => {
          const reason =
            (i18n.language.startsWith("zh")
              ? item.reason_zh || item.reason_en
              : item.reason_en || item.reason_zh) ||
            item.message ||
            t("aidpKnowledge.fileMoveFailed");
          return {
            fileUuid: item.file_uuid,
            fileName: fileNameByUuid.get(item.file_uuid) || item.file_uuid,
            reason,
          };
        });
        const successCount = Math.max(
          0,
          result.summary?.success ?? fileUuids.length - failedItems.length
        );
        const requestedKeys = new Set(
          fileUuids.map((fileUuid) => `file:${fileUuid}`)
        );
        const failedKeys = new Set(
          failedItems.map((item) => `file:${item.fileUuid}`)
        );
        // Successful rows leave the selection; failed rows stay checked so a
        // retry starts from the same set. Unrelated selections are untouched.
        setSelectedFileKeys((current) =>
          current.filter(
            (key) =>
              !requestedKeys.has(String(key)) || failedKeys.has(String(key))
          )
        );
        if (failedItems.length > 0) {
          setMoveFailures({
            successCount,
            failedCount: failedItems.length,
            targetFolder,
            items: failedItems,
          });
        } else {
          message.success(
            t("aidpKnowledge.fileMoveSuccessCount", {
              count: fileUuids.length,
            })
          );
        }
        refreshAll();
      } catch (error) {
        log.error("Failed to move AIDP files:", {
          id: knowledgeBase.kds_id,
          fileUuids,
          targetFolder,
          error,
        });
        const reason = getAidpErrorMessage(
          error,
          t,
          t("aidpKnowledge.fileMoveFailed")
        );
        setMoveFailures({
          successCount: 0,
          failedCount: fileUuids.length,
          targetFolder,
          items: fileUuids.map((fileUuid) => ({
            fileUuid,
            fileName: fileNameByUuid.get(fileUuid) || fileUuid,
            reason,
          })),
        });
      } finally {
        setMovingFileUuids([]);
      }
    },
    [
      currentPath,
      fileNameByUuid,
      i18n.language,
      knowledgeBase.kds_id,
      message,
      refreshAll,
      t,
    ]
  );

  const handleFileDragStart = useCallback(
    (event: React.DragEvent<HTMLElement>) => {
      if (selectedFileUuids.length === 0) {
        event.preventDefault();
        return;
      }
      if (selectedMovableUuids.length !== selectedFileUuids.length) {
        event.preventDefault();
        message.warning(
          t("aidpKnowledge.statusActionBlocked", {
            count: selectedFileUuids.length - selectedMovableUuids.length,
          })
        );
        return;
      }
      const target = event.target as HTMLElement;
      const interactive = target.closest(
        "button, a, input, textarea, select, .ant-checkbox-wrapper"
      ) as HTMLElement | null;
      if (interactive && !interactive.hasAttribute("data-aidp-file-name")) {
        event.preventDefault();
        return;
      }
      writeAidpFileMoveDrag(event.dataTransfer, selectedMovableUuids);
      const names = selectedMovableUuids.map(
        (fileUuid) => fileNameByUuid.get(fileUuid) || fileUuid
      );
      setAidpFileMoveDragImage(
        event.dataTransfer,
        names.length === 1
          ? names[0]
          : t("aidpKnowledge.fileDragSummary", {
              name: names[0],
              count: names.length,
            })
      );
    },
    [fileNameByUuid, message, selectedFileUuids, selectedMovableUuids, t]
  );

  const handleFileDragEnd = useCallback(() => {
    setDragOverFolderKey(null);
    setBreadcrumbDropPath(null);
  }, []);

  const handleInternalMoveDrop = useCallback(
    (
      event: React.DragEvent<HTMLElement>,
      targetFolder: string,
      afterDrop?: () => void
    ) => {
      if (!hasAidpFileMoveDrag(event.dataTransfer)) return;
      event.preventDefault();
      event.stopPropagation();
      const fileUuids = readAidpFileMoveDrag(event.dataTransfer);
      setDragOverFolderKey(null);
      setBreadcrumbDropPath(null);
      afterDrop?.();
      if (fileUuids.length > 0) void performFileMove(fileUuids, targetFolder);
    },
    [performFileMove]
  );

  const handleFolderRowDragOver = useCallback(
    (event: React.DragEvent<HTMLElement>, rowKey: string) => {
      if (!hasAidpFileMoveDrag(event.dataTransfer)) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "move";
      setDragOverFolderKey(rowKey);
    },
    []
  );

  const handleFolderRowDragLeave = useCallback(
    (event: React.DragEvent<HTMLElement>) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
        setDragOverFolderKey(null);
      }
    },
    []
  );

  const getTableRowProps = useCallback(
    (record: FileTableRecord) => {
      if (record.kind === "folder") {
        return {
          className:
            dragOverFolderKey === record.key ? "bg-blue-50" : undefined,
          onDragOver: (event: React.DragEvent<HTMLElement>) =>
            handleFolderRowDragOver(event, record.key),
          onDragLeave: handleFolderRowDragLeave,
          onDrop: (event: React.DragEvent<HTMLElement>) =>
            handleInternalMoveDrop(event, record.path, () =>
              setDragOverFolderKey(null)
            ),
        };
      }
      const selected =
        Boolean(record.file.file_uuid) &&
        selectedFileUuids.includes(record.file.file_uuid as string);
      const canMove = permissionsForFile(record.file)?.canMove === true;
      return {
        draggable:
          canEdit && selected && canMove && movingFileUuids.length === 0
            ? true
            : undefined,
        onDragStart: canEdit && selected ? handleFileDragStart : undefined,
        onDragEnd: handleFileDragEnd,
        className: canEdit && selected && canMove ? "cursor-grab" : undefined,
      };
    },
    [
      canEdit,
      dragOverFolderKey,
      handleFileDragEnd,
      handleFileDragStart,
      handleFolderRowDragLeave,
      handleFolderRowDragOver,
      handleInternalMoveDrop,
      movingFileUuids.length,
      permissionsForFile,
      selectedFileUuids,
    ]
  );

  const hasContent = rows.length > 0;
  const showEmptyState =
    !displayedLoading &&
    !displayedError &&
    !hasContent &&
    (globalSearchActive ? searchQuery.isSuccess : treeQuery.isSuccess);

  const handleDownload = useCallback(
    async (file: AidpFolderFileItem) => {
      if (!file.file_uuid) return;
      try {
        const response = await aidpKnowledgeService.downloadDoc(
          knowledgeBase.kds_id,
          file.file_uuid
        );
        const blobUrl = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = blobUrl;
        link.download = getAidpDownloadFilename(response.headers, {
          file_name: file.file_name || "",
          file_type: file.file_type,
        });
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(blobUrl);
      } catch (error) {
        log.error("Failed to download AIDP file:", {
          id: knowledgeBase.kds_id,
          fileUuid: file.file_uuid,
          error,
        });
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.downloadFailed"))
        );
      }
    },
    [knowledgeBase.kds_id, message, t]
  );

  const handleDeleteFile = useCallback(
    (file: AidpFolderFileItem) => {
      if (!file.file_uuid) return;
      setDeleteConfirmOpen(true);
      void Promise.resolve(
        modal.confirm({
          title: t("aidpKnowledge.deleteFileTitle"),
          centered: true,
          okText: t("common.delete"),
          cancelText: t("common.cancel"),
          okButtonProps: { danger: true },
          afterClose: () => setDeleteConfirmOpen(false),
          content: t("aidpKnowledge.deleteFileContent", {
            name: file.file_name,
          }),
          onOk: async () => {
            try {
              const result = await aidpKnowledgeService.removeDoc(
                knowledgeBase.kds_id,
                file.file_uuid as string
              );
              const failed = result.failed_list.find(
                (item) => item.file_uuid === file.file_uuid
              );
              if (
                failed ||
                result.summary.failed > 0 ||
                !result.success_list.some(
                  (item) => item.file_uuid === file.file_uuid
                )
              ) {
                const reason =
                  (i18n.language.startsWith("zh")
                    ? failed?.reason_zh || failed?.reason_en
                    : failed?.reason_en || failed?.reason_zh) ||
                  failed?.message ||
                  failed?.reason ||
                  t("aidpKnowledge.deleteDocFailed");
                const code = failed?.error_code ?? failed?.code;
                throw code ? new ApiError(code, reason) : new Error(reason);
              }
              message.success(t("aidpKnowledge.deleteDocSuccess"));
              refreshAll();
            } catch (error) {
              log.error("Failed to delete AIDP file:", {
                id: knowledgeBase.kds_id,
                fileUuid: file.file_uuid,
                error,
              });
              message.error(
                getAidpErrorMessage(
                  error,
                  t,
                  t("aidpKnowledge.deleteDocFailed")
                )
              );
              throw error;
            }
          },
        })
      ).catch(() => undefined);
    },
    [i18n.language, knowledgeBase.kds_id, message, modal, refreshAll, t]
  );

  const handleBatchDeleteFiles = useCallback(() => {
    if (selectedFileUuids.length === 0) return;
    if (selectedDeletableUuids.length !== selectedFileUuids.length) {
      message.warning(
        t("aidpKnowledge.statusActionBlocked", {
          count: selectedFileUuids.length - selectedDeletableUuids.length,
        })
      );
      return;
    }
    const fileUuids = selectedDeletableUuids;
    if (fileUuids.length > AIDP_BATCH_DELETE_MAX) {
      message.warning(
        t("aidpKnowledge.deleteDocsLimit", { max: AIDP_BATCH_DELETE_MAX })
      );
      return;
    }
    setDeleteConfirmOpen(true);
    void Promise.resolve(
      modal.confirm({
        title: t("aidpKnowledge.deleteFilesTitle"),
        centered: true,
        okText: t("common.delete"),
        cancelText: t("common.cancel"),
        okButtonProps: { danger: true },
        afterClose: () => setDeleteConfirmOpen(false),
        content: t("aidpKnowledge.deleteFilesContent", {
          count: fileUuids.length,
        }),
        onOk: async () => {
          try {
            const result = await aidpKnowledgeService.removeDocs(
              knowledgeBase.kds_id,
              fileUuids
            );
            const { success, failed } = result.summary;
            if (failed === 0) {
              message.success(t("aidpKnowledge.deleteDocSuccess"));
            } else if (success === 0) {
              const first = result.failed_list[0];
              const reason =
                (i18n.language.startsWith("zh")
                  ? first?.reason_zh || first?.reason_en
                  : first?.reason_en || first?.reason_zh) ||
                first?.message ||
                first?.reason ||
                t("aidpKnowledge.deleteDocFailed");
              const code = first?.error_code ?? first?.code;
              throw code ? new ApiError(code, reason) : new Error(reason);
            } else {
              message.warning(
                t("aidpKnowledge.deleteDocsPartial", { success, failed })
              );
            }
            setSelectedFileKeys([]);
            refreshAll();
          } catch (error) {
            log.error("Failed to batch delete AIDP files:", {
              id: knowledgeBase.kds_id,
              count: fileUuids.length,
              error,
            });
            message.error(
              getAidpErrorMessage(error, t, t("aidpKnowledge.deleteDocFailed"))
            );
            throw error;
          }
        },
      })
    ).catch(() => undefined);
  }, [
    i18n.language,
    knowledgeBase.kds_id,
    message,
    modal,
    refreshAll,
    selectedDeletableUuids,
    selectedFileUuids,
    t,
  ]);

  const handleDeleteFolder = useCallback(
    async (target: AidpFolderNodeTarget) => {
      let hasContents = false;
      try {
        const contents = await aidpKnowledgeService.getFolderTree(
          knowledgeBase.kds_id,
          target.path,
          1,
          1,
          "",
          true
        );
        hasContents =
          (contents.folders?.length ?? 0) > 0 ||
          (contents.files?.total ?? 0) > 0;
      } catch (error) {
        log.error("Failed to inspect AIDP folder before delete:", {
          id: knowledgeBase.kds_id,
          path: target.path,
          error,
        });
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.folderDeleteFailed"))
        );
        return;
      }
      if (hasContents) {
        message.warning(t("aidpKnowledge.folderDeleteNotEmpty"));
        return;
      }
      setDeleteConfirmOpen(true);
      void Promise.resolve(
        modal.confirm({
          title: t("aidpKnowledge.folderDeleteTitle"),
          centered: true,
          okText: t("common.delete"),
          cancelText: t("common.cancel"),
          afterClose: () => setDeleteConfirmOpen(false),
          content: t("aidpKnowledge.folderDeleteContent", {
            name: target.name,
          }),
          onOk: async () => {
            try {
              await aidpKnowledgeService.deleteFolder(
                knowledgeBase.kds_id,
                target.path
              );
              message.success(t("aidpKnowledge.folderDeleteSuccess"));
              if (
                currentPath === target.path ||
                currentPath.startsWith(`${target.path}/`)
              ) {
                openFolder(parentFolderPath(target.path));
              }
              refreshAll();
            } catch (error) {
              log.error("Failed to delete AIDP folder:", {
                id: knowledgeBase.kds_id,
                path: target.path,
                error,
              });
              message.error(
                getAidpErrorMessage(
                  error,
                  t,
                  t("aidpKnowledge.folderDeleteFailed")
                )
              );
              throw error;
            }
          },
        })
      ).catch(() => undefined);
    },
    [
      currentPath,
      knowledgeBase.kds_id,
      message,
      modal,
      openFolder,
      refreshAll,
      t,
    ]
  );

  const submitFolderName = useCallback(
    async (name: string) => {
      if (!folderNameDialog) return;
      setFolderNameSaving(true);
      try {
        if (folderNameDialog.mode === "create") {
          await aidpKnowledgeService.createFolder(
            knowledgeBase.kds_id,
            folderNameDialog.parentPath,
            name
          );
          message.success(t("aidpKnowledge.folderCreateSuccess"));
        } else {
          const { target } = folderNameDialog;
          const parent = parentFolderPath(target.path);
          const result = await aidpKnowledgeService.renameFolder(
            knowledgeBase.kds_id,
            parent,
            target.name,
            name
          );
          const newPath = result.folder_path || joinFolderPath(parent, name);
          message.success(t("aidpKnowledge.folderRenameSuccess"));
          if (
            currentPath === target.path ||
            currentPath.startsWith(`${target.path}/`)
          ) {
            setCurrentPath(
              replaceFolderPrefix(currentPath, target.path, newPath)
            );
          }
        }
        setFolderNameDialog(null);
        refreshAll();
      } catch (error) {
        log.error("Failed to save AIDP folder name:", {
          id: knowledgeBase.kds_id,
          dialog: folderNameDialog,
          error,
        });
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.folderSaveFailed"))
        );
      } finally {
        setFolderNameSaving(false);
      }
    },
    [
      currentPath,
      folderNameDialog,
      knowledgeBase.kds_id,
      message,
      refreshAll,
      t,
    ]
  );

  const handleMoveFolder = useCallback(
    async (targetFolder: string) => {
      const target = folderMoveTarget;
      if (!target) return;
      const parent = parentFolderPath(target.path);
      if (targetFolder === parent) {
        setFolderMoveTarget(null);
        return;
      }
      setFolderMoveTarget(null);

      const runMove = async (mergeOnConflict: boolean) => {
        const result = await aidpKnowledgeService.moveFolder(
          knowledgeBase.kds_id,
          parent,
          target.name,
          targetFolder,
          mergeOnConflict
        );
        const newPath =
          result.folder_path || joinFolderPath(targetFolder, target.name);
        if (
          currentPath === target.path ||
          currentPath.startsWith(`${target.path}/`)
        ) {
          setCurrentPath(
            replaceFolderPrefix(currentPath, target.path, newPath)
          );
        }
        const conflicts = Array.isArray(result.conflict_paths)
          ? result.conflict_paths.length
          : 0;
        if (conflicts > 0) {
          message.warning(
            t("aidpKnowledge.folderMergeConflicts", { count: conflicts })
          );
        } else {
          message.success(t("aidpKnowledge.folderMoveSuccess"));
        }
        refreshAll();
      };

      try {
        await runMove(false);
      } catch (error) {
        if (isAidpNameConflictError(error)) {
          modal.confirm({
            title: t("aidpKnowledge.folderMergeTitle"),
            content: t("aidpKnowledge.folderMergeContent", {
              name: target.name,
            }),
            okText: t("aidpKnowledge.folderMergeConfirm"),
            cancelText: t("common.cancel"),
            onOk: async () => {
              try {
                await runMove(true);
              } catch (mergeError) {
                log.error("Failed to merge AIDP folder:", {
                  id: knowledgeBase.kds_id,
                  path: target.path,
                  targetFolder,
                  mergeError,
                });
                message.error(
                  getAidpErrorMessage(
                    mergeError,
                    t,
                    t("aidpKnowledge.folderMergeFailed")
                  )
                );
              }
            },
          });
          return;
        }
        log.error("Failed to move AIDP folder:", {
          id: knowledgeBase.kds_id,
          path: target.path,
          targetFolder,
          error,
        });
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.folderMoveFailed"))
        );
      }
    },
    [
      currentPath,
      folderMoveTarget,
      knowledgeBase.kds_id,
      message,
      modal,
      refreshAll,
      t,
    ]
  );

  const handleMoveFile = useCallback(
    async (targetFolder: string) => {
      const request = fileMoveRequest;
      if (!request) return;
      setFileMoveRequest(null);
      await performFileMove(request.fileUuids, targetFolder);
    },
    [fileMoveRequest, performFileMove]
  );

  const handleRenameFile = useCallback(
    async (name: string) => {
      const file = fileRenameTarget;
      if (!file?.file_uuid) return;
      if (name === file.file_name) {
        setFileRenameTarget(null);
        return;
      }
      setFileRenameSaving(true);
      try {
        await aidpKnowledgeService.renameFile(
          knowledgeBase.kds_id,
          file.file_uuid,
          name
        );
        message.success(t("aidpKnowledge.fileRenameSuccess"));
        setFileRenameTarget(null);
        refreshAll();
      } catch (error) {
        log.error("Failed to rename AIDP file:", {
          id: knowledgeBase.kds_id,
          fileUuid: file.file_uuid,
          error,
        });
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.fileRenameFailed"))
        );
      } finally {
        setFileRenameSaving(false);
      }
    },
    [fileRenameTarget, knowledgeBase.kds_id, message, refreshAll, t]
  );

  const folderMenuItems = useCallback((): NonNullable<MenuProps["items"]> => {
    if (!canEdit) return [];
    return [
      {
        key: "create",
        icon: <FolderOpenOutlined />,
        label: t("aidpKnowledge.folderCreate"),
      },
      {
        key: "rename",
        icon: <EditOutlined />,
        label: t("aidpKnowledge.folderRename"),
      },
      {
        key: "move",
        icon: <FolderOpenOutlined />,
        label: t("aidpKnowledge.folderMove"),
      },
      {
        key: "delete",
        icon: <DeleteOutlined />,
        label: t("aidpKnowledge.folderDelete"),
      },
    ];
  }, [canEdit, t]);

  const handleFolderMenuClick = useCallback(
    (row: FolderTableRow, key: string) => {
      const target: AidpFolderNodeTarget = {
        path: row.path,
        name: row.name,
      };
      if (key === "create")
        setFolderNameDialog({ mode: "create", parentPath: row.path });
      if (key === "rename") setFolderNameDialog({ mode: "rename", target });
      if (key === "move") setFolderMoveTarget(target);
      if (key === "delete") handleDeleteFolder(target);
    },
    [handleDeleteFolder]
  );

  const handleRetryFile = useCallback(
    async (file: AidpFolderFileItem) => {
      if (!file.file_uuid) return;
      setRetryingFileUuid(file.file_uuid);
      try {
        const result = await aidpKnowledgeService.retryUploadTasks(
          knowledgeBase.kds_id,
          [file.file_uuid]
        );
        if (result.summary.failed > 0) {
          const first = result.failed_list[0];
          const reason =
            (i18n.language.startsWith("zh")
              ? first?.reason_zh || first?.reason_en
              : first?.reason_en || first?.reason_zh) ||
            first?.message ||
            first?.reason ||
            t("aidpKnowledge.retryTaskFailed");
          throw new Error(reason);
        }
        message.success(t("aidpKnowledge.retryTaskSuccess"));
        refreshAll();
      } catch (error) {
        log.error("Failed to retry AIDP file:", {
          id: knowledgeBase.kds_id,
          fileUuid: file.file_uuid,
          error,
        });
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.retryTaskFailed"))
        );
      } finally {
        setRetryingFileUuid(null);
      }
    },
    [i18n.language, knowledgeBase.kds_id, message, refreshAll, t]
  );

  const fileMenuItems = useCallback(
    (file: AidpFolderFileItem): NonNullable<MenuProps["items"]> => {
      if (!canEdit) return [];
      const permissions = permissionsForFile(file);
      const items: NonNullable<MenuProps["items"]> = [];
      if (permissions?.canMove) {
        items.push({
          key: "move",
          icon: <FolderOpenOutlined />,
          label: t("aidpKnowledge.fileMove"),
        });
      }
      if (permissions?.canRename) {
        items.push({
          key: "rename",
          icon: <EditOutlined />,
          label: t("aidpKnowledge.fileRename"),
        });
      }
      if (permissions?.canRetry) {
        items.push({
          key: "retry",
          icon: <ReloadOutlined spin={retryingFileUuid === file.file_uuid} />,
          label: t("aidpKnowledge.retryTask"),
        });
      }
      return items;
    },
    [canEdit, permissionsForFile, retryingFileUuid, t]
  );

  const handleFileMenuClick = useCallback(
    (file: AidpFolderFileItem, key: string) => {
      if (key === "move" && file.file_uuid) {
        setFileMoveRequest({
          fileUuids: [file.file_uuid],
          title: t("aidpKnowledge.fileMoveTitle", {
            name: file.file_name || "",
          }),
        });
      }
      if (key === "rename") setFileRenameTarget(file);
      if (key === "retry") void handleRetryFile(file);
    },
    [handleRetryFile, t]
  );

  const baseColumns: ColumnsType<FileTableRecord> = [
    {
      title: t("aidpKnowledge.detailFileName"),
      key: "file_name",
      fixed: "left",
      width: 230,
      ellipsis: true,
      render: (_value, record) =>
        record.kind === "folder" ? (
          <button
            type="button"
            className="flex max-w-full items-center gap-2 truncate text-left text-blue-600 hover:text-blue-700 hover:underline"
            onClick={() => openFolder(record.path)}
          >
            <FolderOutlined className="shrink-0 text-[#1677ff]" />
            <span className="truncate">{record.name}</span>
          </button>
        ) : (
          <Tooltip title={t("common.preview")}>
            <button
              type="button"
              disabled={
                !record.file.file_uuid ||
                !folderTreeStatusMeta(record.file.status)?.permissions
                  .canPreview
              }
              data-aidp-file-name="true"
              className="flex max-w-full items-center gap-2 truncate text-left text-blue-600 hover:text-blue-700 hover:underline disabled:cursor-default disabled:text-gray-500 disabled:no-underline"
              onClick={() => setPreviewFile(toDocumentItem(record.file))}
            >
              <FileTextOutlined className="shrink-0 text-blue-500" />
              <span className="truncate">{record.name || "-"}</span>
            </button>
          </Tooltip>
        ),
    },
    {
      title: t("aidpKnowledge.detailFileType"),
      key: "file_type",
      width: 60,
      render: (_value, record) =>
        record.kind === "folder"
          ? t("aidpKnowledge.folderTypeFolder")
          : record.file.file_type || "-",
    },
    {
      title: t("aidpKnowledge.detailFileSize"),
      key: "file_size",
      width: 70,
      render: (_value, record) =>
        record.kind === "folder" ? "-" : formatFileSize(record.file.file_size),
    },
    {
      title: t("aidpKnowledge.detailCreatedAt"),
      key: "created_at",
      width: 130,
      ellipsis: true,
      render: (_value, record) =>
        record.kind === "folder"
          ? "-"
          : formatDetailDateTime(
              record.file.created_at || record.file.first_upload_time
            ),
    },
    {
      title: t("aidpKnowledge.detailUpdateTime"),
      key: "updated_at",
      width: 130,
      ellipsis: true,
      render: (_value, record) =>
        record.kind === "folder"
          ? "-"
          : formatDetailDateTime(
              record.file.updated_at || record.file.update_time
            ),
    },
    {
      title: t("aidpKnowledge.detailFileStatus"),
      key: "file_status",
      width: 90,
      render: (_value, record) => {
        if (record.kind === "folder") return "-";
        const meta = folderTreeStatusMeta(record.file.status);
        if (!meta) return "-";
        return (
          <span className="inline-flex items-center gap-2 whitespace-nowrap text-gray-700">
            <i className={`h-2 w-2 shrink-0 rounded-full ${meta.dotClass}`} />
            {meta.labelKey ? t(meta.labelKey) : record.file.status}
          </span>
        );
      },
    },
    {
      title: t("aidpKnowledge.detailOperation"),
      key: "actions",
      fixed: "right",
      width: 120,
      render: (_value, record) => {
        if (record.kind === "folder") {
          const items = folderMenuItems();
          return items.length > 0 ? (
            <Tooltip title={t("aidpKnowledge.moreOperations")}>
              <Dropdown
                trigger={["click"]}
                menu={{
                  items,
                  onClick: ({ key }) => handleFolderMenuClick(record, key),
                }}
              >
                <Button
                  type="text"
                  size="small"
                  icon={<MoreOutlined />}
                  aria-label={t("aidpKnowledge.moreOperations")}
                />
              </Dropdown>
            </Tooltip>
          ) : (
            <Button
              type="link"
              size="small"
              className="px-0"
              onClick={() => openFolder(record.path)}
            >
              {t("aidpKnowledge.folderOpen")}
            </Button>
          );
        }
        const permissions = folderTreeStatusMeta(
          record.file.status
        )?.permissions;
        const menuItems = fileMenuItems(record.file);
        return (
          <div className="flex items-center gap-2 whitespace-nowrap">
            <Tooltip title={t("aidpKnowledge.download")}>
              <Button
                type="text"
                size="small"
                icon={<DownloadOutlined />}
                disabled={!record.file.file_uuid || !permissions?.canDownload}
                aria-label={t("aidpKnowledge.download")}
                onClick={() => void handleDownload(record.file)}
              />
            </Tooltip>
            {canEdit && permissions?.canDelete && (
              <Tooltip title={t("common.delete")}>
                <Button
                  type="text"
                  size="small"
                  icon={<DeleteOutlined />}
                  aria-label={t("common.delete")}
                  onClick={() => handleDeleteFile(record.file)}
                />
              </Tooltip>
            )}
            {canEdit && menuItems.length > 0 && (
              <Tooltip title={t("aidpKnowledge.moreOperations")}>
                <Dropdown
                  trigger={["click"]}
                  menu={{
                    items: menuItems,
                    onClick: ({ key }) => handleFileMenuClick(record.file, key),
                  }}
                >
                  <Button
                    type="text"
                    size="small"
                    icon={<MoreOutlined />}
                    aria-label={t("aidpKnowledge.moreOperations")}
                  />
                </Dropdown>
              </Tooltip>
            )}
          </div>
        );
      },
    },
  ];
  const columns = withResizableHeaders(
    baseColumns,
    columnWidths,
    FILE_COLUMN_MIN_WIDTHS,
    setColumnWidths
  );

  const getBreadcrumbDropProps = useCallback(
    (path: string) => ({
      className: `hover:text-blue-600 ${
        breadcrumbDropPath === path
          ? "rounded bg-blue-50 px-1 text-blue-600"
          : ""
      }`,
      onDragOver: (event: React.DragEvent<HTMLButtonElement>) => {
        if (!hasAidpFileMoveDrag(event.dataTransfer)) return;
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = "move";
        setBreadcrumbDropPath(path);
      },
      onDragLeave: () => setBreadcrumbDropPath(null),
      onDrop: (event: React.DragEvent<HTMLButtonElement>) =>
        handleInternalMoveDrop(event, path, () => setBreadcrumbDropPath(null)),
    }),
    [breadcrumbDropPath, handleInternalMoveDrop]
  );

  const segments = folderPathSegments(currentPath);
  const folderLabel =
    segments.length > 0
      ? segments[segments.length - 1].label
      : knowledgeBase.kds_name;
  const fileRenameName = splitFileNameExtension(fileRenameTarget?.file_name);

  return (
    <section className="flex min-h-[420px] grow shrink-0 basis-auto flex-col bg-white">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Input
          allowClear
          prefix={<SearchOutlined className="text-gray-400" />}
          value={globalKeywordInput}
          onChange={(event) => setGlobalKeywordInput(event.target.value)}
          placeholder={t("aidpKnowledge.detailFileSearchAll")}
          style={{ width: 240, maxWidth: "100%" }}
        />
        <div className="flex items-center gap-2">
          <Tooltip title={t("aidpKnowledge.refresh")}>
            <Button
              aria-label={t("aidpKnowledge.refresh")}
              icon={<ReloadOutlined spin={displayedLoading} />}
              onClick={refreshAll}
            />
          </Tooltip>
          {canEdit && (
            <Button
              icon={<FolderOpenOutlined />}
              aria-label={t("aidpKnowledge.fileMoveAction")}
              disabled={
                selectedFileUuids.length === 0 || movingFileUuids.length > 0
              }
              onClick={() => {
                if (selectedMovableUuids.length !== selectedFileUuids.length) {
                  message.warning(
                    t("aidpKnowledge.statusActionBlocked", {
                      count:
                        selectedFileUuids.length - selectedMovableUuids.length,
                    })
                  );
                  return;
                }
                setFileMoveRequest({
                  fileUuids: selectedMovableUuids,
                  title: t("aidpKnowledge.fileMoveTitleCount", {
                    count: selectedMovableUuids.length,
                  }),
                });
              }}
            >
              {t("aidpKnowledge.fileMoveAction")}
            </Button>
          )}
          {canEdit && (
            <Button
              disabled={selectedFileUuids.length === 0}
              onClick={handleBatchDeleteFiles}
            >
              {t("common.delete")}
            </Button>
          )}
          {canEdit && isAvailable && (
            <Button
              type="primary"
              icon={<UploadOutlined />}
              onClick={() => openImport(currentPath)}
            >
              {t("aidpKnowledge.importFile")}
            </Button>
          )}
        </div>
      </div>

      {displayedError && (
        <Alert type="error" showIcon title={displayedError} className="mb-4" />
      )}

      {moveFailures && (
        <Alert
          type={moveFailures.successCount > 0 ? "warning" : "error"}
          showIcon
          closable
          onClose={() => setMoveFailures(null)}
          className="mb-4"
          title={t("aidpKnowledge.fileMoveResultTitle", {
            success: moveFailures.successCount,
            failed: moveFailures.failedCount,
          })}
          description={
            <div>
              <div className="mb-1 text-xs text-gray-500">
                {t("aidpKnowledge.fileMoveFailureTarget", {
                  folder: moveFailures.targetFolder,
                })}
              </div>
              <ul className="max-h-40 overflow-auto">
                {moveFailures.items.map((item) => (
                  <li key={item.fileUuid}>
                    <span className="font-medium">{item.fileName}</span>
                    {"："}
                    {item.reason}
                  </li>
                ))}
              </ul>
            </div>
          }
        />
      )}

      <div className="flex min-h-0 flex-auto gap-4 border-b border-gray-200">
        <aside
          className={`min-h-[240px] w-[240px] min-w-[200px] shrink-0 overflow-auto border-r border-gray-200 pr-2 ${panelStyles.folderRail}`}
        >
          <AidpFolderTree
            knowledgeBaseId={knowledgeBase.kds_id}
            rootLabel={knowledgeBase.kds_name}
            selectedPath={currentPath}
            onSelect={openFolder}
            reloadToken={treeReloadToken}
            onDropFiles={
              canEdit && isAvailable
                ? (path, droppedFiles) => openImport(path, droppedFiles)
                : undefined
            }
            onMoveFiles={
              canEdit && isAvailable
                ? (path, fileUuids) => void performFileMove(fileUuids, path)
                : undefined
            }
            onCreateFolder={
              canEdit
                ? (parentPath) =>
                    setFolderNameDialog({ mode: "create", parentPath })
                : undefined
            }
            onRenameFolder={
              canEdit
                ? (target) => setFolderNameDialog({ mode: "rename", target })
                : undefined
            }
            onMoveFolder={canEdit ? setFolderMoveTarget : undefined}
            onDeleteFolder={canEdit ? handleDeleteFolder : undefined}
          />
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          {segments.length > 0 && (
            <div className="mb-2 flex flex-wrap items-center gap-1 text-xs text-gray-500">
              <button
                type="button"
                {...getBreadcrumbDropProps("/")}
                onClick={() => openFolder("/")}
              >
                {knowledgeBase.kds_name}
              </button>
              {segments.map((segment) => (
                <React.Fragment key={segment.path}>
                  <span>/</span>
                  <button
                    type="button"
                    {...getBreadcrumbDropProps(segment.path)}
                    onClick={() => openFolder(segment.path)}
                  >
                    {segment.label}
                  </button>
                </React.Fragment>
              ))}
            </div>
          )}

          {!globalSearchActive && (
            <div className="mb-2 flex items-center justify-end gap-2">
              {folderSearchOpen ? (
                <Input
                  allowClear
                  autoFocus
                  size="small"
                  prefix={<SearchOutlined className="text-gray-400" />}
                  value={folderKeywordInput}
                  onChange={(event) =>
                    setFolderKeywordInput(event.target.value)
                  }
                  placeholder={t("aidpKnowledge.detailFileSearchInFolder")}
                  style={{ width: 220 }}
                />
              ) : (
                <Tooltip title={t("aidpKnowledge.detailFileSearchInFolder")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<SearchOutlined />}
                    aria-label={t("aidpKnowledge.detailFileSearchInFolder")}
                    onClick={() => setFolderSearchOpen(true)}
                  />
                </Tooltip>
              )}
            </div>
          )}

          {showEmptyState ? (
            <AidpFilesEmptyState
              keyword={globalSearchActive ? globalKeyword : folderKeyword}
              folderLabel={folderLabel}
              isRoot={currentPath === "/"}
              canUpload={canEdit && isAvailable}
              onDropFiles={(droppedFiles) =>
                openImport(currentPath, droppedFiles)
              }
            />
          ) : (
            <>
              <Table<FileTableRecord>
                rowKey={(record) => record.key}
                columns={columns}
                dataSource={rows}
                loading={displayedLoading}
                onRow={(record) => getTableRowProps(record)}
                rowSelection={
                  canEdit
                    ? {
                        selectedRowKeys: selectedFileKeys,
                        onChange: (keys) => setSelectedFileKeys(keys),
                        getCheckboxProps: (record) => {
                          if (record.kind === "folder") {
                            return { disabled: true };
                          }
                          const permissions = folderTreeStatusMeta(
                            record.file.status
                          )?.permissions;
                          return {
                            disabled:
                              !permissions ||
                              (!permissions.canDelete && !permissions.canMove),
                          };
                        },
                      }
                    : undefined
                }
                pagination={false}
                components={{
                  header: { cell: AidpResizableTitle },
                }}
                scroll={{ x: sumColumnWidths(columns) }}
                size="middle"
              />
              <div className="mt-4 shrink-0 border-t border-gray-200 py-3">
                <AidpPagination
                  currentPage={
                    globalSearchActive ? searchPageParams.page : pageParams.page
                  }
                  pageSize={
                    globalSearchActive
                      ? searchPageParams.pageSize
                      : pageParams.pageSize
                  }
                  total={displayedTotal}
                  totalReliable={
                    globalSearchActive
                      ? Boolean(searchQuery.data?.total_reliable)
                      : true
                  }
                  hasMore={
                    globalSearchActive
                      ? Boolean(searchQuery.data?.has_more)
                      : pageParams.page * pageParams.pageSize < fileTotal
                  }
                  selectedCount={selectedFileKeys.length}
                  selectionHint={
                    selectedFileUuids.length > 0
                      ? t("aidpKnowledge.fileDragHintShort")
                      : undefined
                  }
                  onPageChange={(page) =>
                    globalSearchActive
                      ? setSearchPageParams((current) => ({ ...current, page }))
                      : setPageParams((current) => ({ ...current, page }))
                  }
                  onPageSizeChange={(pageSize) =>
                    globalSearchActive
                      ? setSearchPageParams((current) => ({
                          ...current,
                          pageSize,
                          page: 1,
                        }))
                      : setPageParams((current) => ({
                          ...current,
                          pageSize,
                          page: 1,
                        }))
                  }
                />
              </div>
            </>
          )}
        </div>
      </div>

      <AidpImportDrawer
        open={importState.open}
        title={t("aidpKnowledge.importDrawerTitle")}
        knowledgeBase={knowledgeBase}
        defaultFolderPath={importState.target}
        initialFiles={importState.files}
        onClose={() => {
          setImportState({ open: false, target: "/", files: [] });
        }}
        onUploadComplete={refreshAll}
      />

      <AidpFolderNameModal
        open={folderNameDialog !== null}
        title={
          folderNameDialog?.mode === "rename"
            ? t("aidpKnowledge.folderRenameTitle")
            : t("aidpKnowledge.folderCreateTitle")
        }
        label={t("aidpKnowledge.folderNameLabel")}
        initialValue={
          folderNameDialog?.mode === "rename"
            ? folderNameDialog.target.name
            : ""
        }
        placeholder={t("aidpKnowledge.folderNameLabel")}
        confirmLoading={folderNameSaving}
        onCancel={() => setFolderNameDialog(null)}
        onSubmit={(name) => void submitFolderName(name)}
      />

      <AidpFolderPickerModal
        open={folderMoveTarget !== null}
        knowledgeBaseId={knowledgeBase.kds_id}
        rootLabel={knowledgeBase.kds_name}
        title={t("aidpKnowledge.folderMoveTitle", {
          name: folderMoveTarget?.name || "",
        })}
        initialPath={
          folderMoveTarget
            ? parentFolderPath(folderMoveTarget.path)
            : currentPath
        }
        preselect={false}
        invalidPrefix={folderMoveTarget?.path}
        invalidHint={t("aidpKnowledge.folderMoveInvalidHint")}
        onCancel={() => setFolderMoveTarget(null)}
        onSelect={(path) => void handleMoveFolder(path)}
      />

      <AidpFolderPickerModal
        open={fileMoveRequest !== null}
        knowledgeBaseId={knowledgeBase.kds_id}
        rootLabel={knowledgeBase.kds_name}
        title={fileMoveRequest?.title || t("aidpKnowledge.fileMove")}
        initialPath={currentPath}
        preselect={false}
        disabledPath={currentPath}
        disabledHint={t("aidpKnowledge.fileMoveSameFolder")}
        onCancel={() => setFileMoveRequest(null)}
        onSelect={(path) => void handleMoveFile(path)}
      />

      <AidpFolderNameModal
        open={fileRenameTarget !== null}
        title={t("aidpKnowledge.fileRenameTitle")}
        label={t("aidpKnowledge.fileNameLabel")}
        initialValue={fileRenameName.stem}
        suffix={fileRenameName.extension || undefined}
        confirmLoading={fileRenameSaving}
        onCancel={() => setFileRenameTarget(null)}
        onSubmit={(name) => {
          if (/[/\\]/.test(name)) {
            message.error(t("aidpKnowledge.fileNameInvalid"));
            return;
          }
          void handleRenameFile(`${name}${fileRenameName.extension}`);
        }}
      />

      {previewFile && (
        <FilePreviewDrawer
          open
          source="remote"
          objectName={previewFile.file_uuid}
          fileName={previewFile.file_name}
          fileType={previewFile.file_type}
          fileSize={
            typeof previewFile.file_size === "string"
              ? Number(previewFile.file_size)
              : previewFile.file_size
          }
          previewUrl={aidpKnowledgeService.getPreviewUrl(
            knowledgeBase.kds_id,
            previewFile.file_uuid
          )}
          rawStream
          presentation="fullscreen"
          previewContext="knowledgeBase"
          onClose={() => setPreviewFile(null)}
        />
      )}
    </section>
  );
};

export default AidpKnowledgeFilesPanel;
