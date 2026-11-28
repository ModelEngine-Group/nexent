// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { App } from "antd";

import type { AidpDocumentItem, AidpFolderFileItem } from "@/ext_components/aidp/shared/types/management";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  useKbOntologyBinding,
  useOntologyEntityOptions,
  useOntologyMetadataSchema,
} from "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpChunkMetadata";
import { useAidpFolderTree } from "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpFolderTree";
import { useAidpIngestedFileSearch } from "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpIngestedFileSearch";
import type { AidpFolderNodeTarget } from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderTree";
import {
  AIDP_DETAIL_PAGE_SIZE,
  folderTreeStatusMeta,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";
import { joinFolderPath } from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFolderUtils";
import type { AidpDroppedFile } from "@/ext_components/aidp/pages/knowledge-files/utils/aidpDropFiles";
import type {
  AidpKnowledgeFilesPanelProps,
  FileDeleteFailure,
  FileMoveFailure,
  FileMoveRequest,
  FileTableRecord,
  FolderNameDialog,
  FolderTableRow,
  FileTableRow,
} from "../components/AidpKnowledgeFilesPanel.types";

type StateProps = Pick<
  AidpKnowledgeFilesPanelProps,
  "knowledgeBase" | "onFolderChange" | "initialPath" | "pollingPaused" | "onFilesChanged"
>;

export const useAidpFilesPanelState = ({
  knowledgeBase,
  onFolderChange,
  initialPath = "/",
  pollingPaused = false,
  onFilesChanged,
}: StateProps) => {
  const { t, i18n } = useTranslation();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const scope = useAidpQueryScope();

  const [currentPath, setCurrentPath] = useState(initialPath);
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
  const [folderNameError, setFolderNameError] = useState<string | null>(null);
  const [folderMoveTarget, setFolderMoveTarget] =
    useState<AidpFolderNodeTarget | null>(null);
  const [fileMoveRequest, setFileMoveRequest] =
    useState<FileMoveRequest | null>(null);
  const [fileRenameTarget, setFileRenameTarget] =
    useState<AidpFolderFileItem | null>(null);
  const [fileRenameSaving, setFileRenameSaving] = useState(false);
  const [retryingFileUuid, setRetryingFileUuid] = useState<string | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  // Whole-file metadata editing through the batch-metadata file_uuid_list
  // variant; only offered while the KB is bound to an ontology domain.
  const [metadataFile, setMetadataFile] = useState<AidpDocumentItem | null>(
    null
  );
  const [batchMetadataFiles, setBatchMetadataFiles] = useState<
    AidpDocumentItem[] | null
  >(null);
  const [metadataDeleteFiles, setMetadataDeleteFiles] = useState<
    AidpDocumentItem[] | null
  >(null);
  const [tagEditFiles, setTagEditFiles] = useState<AidpDocumentItem[] | null>(
    null
  );
  const [metadataSubmitting, setMetadataSubmitting] = useState(false);
  const bindingQuery = useKbOntologyBinding(knowledgeBase.kds_id);
  const odId = bindingQuery.data?.binding?.od_id ?? null;
  const metadataSchemaQuery = useOntologyMetadataSchema(odId);
  const metadataFields = metadataSchemaQuery.data ?? [];
  const entityOptionsQuery = useOntologyEntityOptions(odId);
  const tagOptions = entityOptionsQuery.data ?? [];
  const [moveFailures, setMoveFailures] = useState<FileMoveFailure | null>(
    null
  );
  const [deleteFailures, setDeleteFailures] =
    useState<FileDeleteFailure | null>(null);
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
    metadataFile !== null ||
    batchMetadataFiles !== null ||
    metadataDeleteFiles !== null ||
    tagEditFiles !== null;

  // Keep the knowledge-base URL in sync with the current folder so browser
  // back from a file detail returns to the same folder instead of the root.
  useEffect(() => {
    if (currentPath === initialPath) return;
    onFolderChange(currentPath);
  }, [currentPath, initialPath, onFolderChange]);

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
    }, 300);
    return () => window.clearTimeout(timer);
  }, [globalKeywordInput]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = folderKeywordInput.trim();
      setFolderKeyword((current) => (current === next ? current : next));
    }, 300);
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
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "folder-tree", knowledgeBase.kds_id],
    });
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ingested-file-search", knowledgeBase.kds_id],
    });
    onFilesChanged?.();
  }, [knowledgeBase.kds_id, onFilesChanged, queryClient, scope.key]);

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

  const hasContent = rows.length > 0;
  const showEmptyState =
    !displayedLoading &&
    !displayedError &&
    !hasContent &&
    (globalSearchActive ? searchQuery.isSuccess : treeQuery.isSuccess);

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

  return {
    t,
    i18n,
    message,
    modal,
    currentPath,
    setCurrentPath,
    globalKeywordInput,
    setGlobalKeywordInput,
    globalKeyword,
    setGlobalKeyword,
    folderKeywordInput,
    setFolderKeywordInput,
    folderKeyword,
    setFolderKeyword,
    folderSearchOpen,
    setFolderSearchOpen,
    pageParams,
    setPageParams,
    searchPageParams,
    setSearchPageParams,
    selectedFileKeys,
    setSelectedFileKeys,
    columnWidths,
    setColumnWidths,
    treeReloadToken,
    importState,
    setImportState,
    folderNameDialog,
    setFolderNameDialog,
    folderNameSaving,
    setFolderNameSaving,
    folderNameError,
    setFolderNameError,
    folderMoveTarget,
    setFolderMoveTarget,
    fileMoveRequest,
    setFileMoveRequest,
    fileRenameTarget,
    setFileRenameTarget,
    fileRenameSaving,
    setFileRenameSaving,
    retryingFileUuid,
    setRetryingFileUuid,
    deleteConfirmOpen,
    setDeleteConfirmOpen,
    metadataFile,
    setMetadataFile,
    batchMetadataFiles,
    setBatchMetadataFiles,
    metadataDeleteFiles,
    setMetadataDeleteFiles,
    tagEditFiles,
    setTagEditFiles,
    metadataSubmitting,
    setMetadataSubmitting,
    bindingQuery,
    odId,
    metadataSchemaQuery,
    metadataFields,
    tagOptions,
    moveFailures,
    setMoveFailures,
    deleteFailures,
    setDeleteFailures,
    movingFileUuids,
    setMovingFileUuids,
    dragOverFolderKey,
    setDragOverFolderKey,
    breadcrumbDropPath,
    setBreadcrumbDropPath,
    dialogOpen,
    treeQuery,
    folders,
    files,
    fileTotal,
    loading,
    fileError,
    globalSearchActive,
    searchQuery,
    searchFiles,
    displayedFiles,
    displayedTotal,
    displayedLoading,
    displayedError,
    refreshAll,
    openFolder,
    openImport,
    rows,
    showEmptyState,
    selectedFileUuids,
    fileNameByUuid,
    permissionsForFile,
    selectedFileItems,
    selectedDeletableUuids,
    selectedMovableUuids,
  };
};

export type AidpFilesPanelState = ReturnType<typeof useAidpFilesPanelState>;
