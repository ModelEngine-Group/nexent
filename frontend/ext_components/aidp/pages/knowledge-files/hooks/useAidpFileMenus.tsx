// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button, Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  FolderOutlined,
  MoreOutlined,
  TagsOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import type { AidpFolderFileItem } from "@/ext_components/aidp/shared/types/management";
import type { AidpFolderNodeTarget } from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderTree";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  formatDetailDateTime,
  formatFileSize,
  folderTreeStatusMeta,
  splitFileNameExtension,
  withResizableHeaders,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";
import log from "@/lib/logger";
import {
  hasAidpFileMoveDrag,
  readAidpFileMoveDrag,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFileDrag";
import {
  folderPathSegments,
  parentFolderPath,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFolderUtils";
import {
  FILE_COLUMN_MIN_WIDTHS,
  localizedFailureReason,
  toDocumentItem,
  type AidpKnowledgeFilesPanelProps,
  type FileTableRecord,
  type FolderTableRow,
} from "../components/AidpKnowledgeFilesPanel.types";
import type { AidpFilesPanelState } from "./useAidpFilesPanelState";
import type { AidpFileActions } from "./useAidpFileActions";

export const useAidpFileMenus = (
  state: AidpFilesPanelState,
  actions: AidpFileActions,
  knowledgeBase: AidpKnowledgeFilesPanelProps["knowledgeBase"],
  canEdit: boolean,
  onOpenFile: AidpKnowledgeFilesPanelProps["onOpenFile"]
) => {
  const {
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
    selectedFileUuids,
    fileNameByUuid,
    permissionsForFile,
    selectedFileItems,
    selectedDeletableUuids,
    selectedMovableUuids,
  } = state;
  const {
    performFileMove,
    handleFileDragStart,
    handleFileDragEnd,
    handleInternalMoveDrop,
    handleFolderRowDragOver,
    handleFolderRowDragLeave,
    getTableRowProps,
    handleDownload,
    stepBackIfPageEmptied,
    handleDeleteFile,
    handleBatchDeleteFiles,
    handleDeleteFolder,
    submitFolderName,
    handleMoveFolder,
    handleMoveFile,
    handleRenameFile,
  } = actions;

  const retryUploadMutation = useMutation({
    mutationFn: (fileUuid: string) =>
      aidpKnowledgeService.retryUploadTasks(knowledgeBase.kds_id, [fileUuid]),
  });
  const saveMetadataMutation = useMutation({
    mutationFn: ({
      odIdValue,
      metadataJson,
      fileUuids,
    }: {
      odIdValue: number;
      metadataJson: Record<string, string>;
      fileUuids: string[];
    }) =>
      aidpKnowledgeService.batchUpdateChunkMetadata(knowledgeBase.kds_id, {
        od_id: odIdValue,
        metadata_json: metadataJson,
        file_uuid_list: fileUuids,
      }),
  });

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
        const result = await retryUploadMutation.mutateAsync(file.file_uuid);
        if (result.summary.failed > 0) {
          const first = result.failed_list[0];
          const reason = localizedFailureReason(
            first,
            i18n.language,
            t("aidpKnowledge.retryTaskFailed")
          );
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
      if (odId !== null && file.file_uuid) {
        items.push(
          {
            key: "metadata-add",
            icon: <TagsOutlined />,
            label: t("aidpKnowledge.batchMetadataTitle"),
            disabled: metadataFields.length === 0,
          },
          {
            key: "metadata-delete",
            icon: <TagsOutlined />,
            label: t("aidpKnowledge.batchMetadataDeleteTitle"),
            disabled: metadataFields.length === 0,
          },
          {
            key: "metadata-tag",
            icon: <TagsOutlined />,
            label: t("aidpKnowledge.batchTagsTitle"),
            disabled: tagOptions.length === 0,
          }
        );
      }
      const metadataActionCount = items.length;
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
      if (metadataActionCount > 0 && items.length > metadataActionCount) {
        items.splice(metadataActionCount, 0, { type: "divider" as const });
      }
      return items;
    },
    [
      canEdit,
      metadataFields.length,
      odId,
      permissionsForFile,
      retryingFileUuid,
      t,
      tagOptions.length,
    ]
  );

  const handleFileMenuClick = useCallback(
    (file: AidpFolderFileItem, key: string) => {
      if (key === "metadata-add") {
        setMetadataFile(toDocumentItem(file));
      }
      if (key === "metadata-delete") {
        setMetadataDeleteFiles([toDocumentItem(file)]);
      }
      if (key === "metadata-tag") {
        setTagEditFiles([toDocumentItem(file)]);
      }
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
    [
      handleRetryFile,
      setMetadataDeleteFiles,
      setMetadataFile,
      setTagEditFiles,
      setFileMoveRequest,
      setFileRenameTarget,
      t,
    ]
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
          <Tooltip title={t("aidpKnowledge.fileDetailTitle")}>
            <button
              type="button"
              disabled={
                !record.file.file_uuid ||
                !folderTreeStatusMeta(record.file.status)?.permissions
                  .canPreview
              }
              data-aidp-file-name="true"
              className="flex max-w-full items-center gap-2 truncate text-left text-blue-600 hover:text-blue-700 hover:underline disabled:cursor-default disabled:text-gray-500 disabled:no-underline"
              onClick={() =>
                onOpenFile(toDocumentItem(record.file), currentPath)
              }
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
      width: 150,
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

  const handleSaveFileMetadata = useCallback(
    async (metadataJson: Record<string, string>) => {
      if (!metadataFile || odId === null) return;
      setMetadataSubmitting(true);
      try {
        await saveMetadataMutation.mutateAsync({
          odIdValue: Number(odId),
          metadataJson,
          fileUuids: [metadataFile.file_uuid],
        });
        message.success(t("aidpKnowledge.fileMetadataSaved"));
        setMetadataFile(null);
        refreshAll();
      } catch (error) {
        message.error(
          getAidpErrorMessage(
            error,
            t,
            t("aidpKnowledge.chunkMetadataSaveFailed")
          )
        );
        throw error;
      } finally {
        setMetadataSubmitting(false);
      }
    },
    [knowledgeBase.kds_id, message, metadataFile, odId, refreshAll, t]
  );

  const handleSaveBatchFileMetadata = useCallback(
    async (metadataJson: Record<string, string>) => {
      const fileUuids = (batchMetadataFiles ?? [])
        .map((file) => file.file_uuid)
        .filter(Boolean);
      if (fileUuids.length === 0 || odId === null) return;
      setMetadataSubmitting(true);
      try {
        await saveMetadataMutation.mutateAsync({
          odIdValue: Number(odId),
          metadataJson,
          fileUuids,
        });
        message.success(t("aidpKnowledge.batchMetadataSaved"));
        setBatchMetadataFiles(null);
        refreshAll();
      } catch (error) {
        message.error(
          getAidpErrorMessage(
            error,
            t,
            t("aidpKnowledge.chunkMetadataSaveFailed")
          )
        );
        throw error;
      } finally {
        setMetadataSubmitting(false);
      }
    },
    [
      batchMetadataFiles,
      knowledgeBase.kds_id,
      message,
      odId,
      refreshAll,
      setBatchMetadataFiles,
      t,
    ]
  );

  const handleDeleteBatchFileMetadata = useCallback(
    async (keys: string[]) => {
      const fileUuids = (metadataDeleteFiles ?? [])
        .map((file) => file.file_uuid)
        .filter(Boolean);
      if (fileUuids.length === 0 || odId === null || keys.length === 0) return;
      setMetadataSubmitting(true);
      try {
        await aidpKnowledgeService.batchUpdateChunkMetadata(
          knowledgeBase.kds_id,
          {
            od_id: Number(odId),
            metadata_json: Object.fromEntries(keys.map((key) => [key, null])),
            file_uuid_list: fileUuids,
          }
        );
        message.success(t("aidpKnowledge.batchMetadataDeleteSaved"));
        setMetadataDeleteFiles(null);
        refreshAll();
      } catch (error) {
        message.error(
          getAidpErrorMessage(
            error,
            t,
            t("aidpKnowledge.batchMetadataDeleteFailed")
          )
        );
        throw error;
      } finally {
        setMetadataSubmitting(false);
      }
    },
    [
      knowledgeBase.kds_id,
      message,
      metadataDeleteFiles,
      odId,
      refreshAll,
      setMetadataDeleteFiles,
      t,
    ]
  );

  const handleSaveBatchFileTags = useCallback(
    async (tags: string[]) => {
      const fileUuids = (tagEditFiles ?? [])
        .map((file) => file.file_uuid)
        .filter(Boolean);
      if (fileUuids.length === 0 || odId === null) return;
      setMetadataSubmitting(true);
      try {
        await aidpKnowledgeService.batchUpdateChunkMetadata(
          knowledgeBase.kds_id,
          {
            od_id: Number(odId),
            tag: tags,
            file_uuid_list: fileUuids,
          }
        );
        message.success(t("aidpKnowledge.batchTagsSaved"));
        setTagEditFiles(null);
        refreshAll();
      } catch (error) {
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.batchTagsFailed"))
        );
        throw error;
      } finally {
        setMetadataSubmitting(false);
      }
    },
    [
      knowledgeBase.kds_id,
      message,
      odId,
      refreshAll,
      setTagEditFiles,
      tagEditFiles,
      t,
    ]
  );

  const segments = folderPathSegments(currentPath);
  const folderLabel =
    segments.length > 0
      ? segments[segments.length - 1].label
      : knowledgeBase.kds_name;
  const fileRenameName = splitFileNameExtension(fileRenameTarget?.file_name);

  return {
    columns,
    segments,
    folderLabel,
    fileRenameName,
    folderMenuItems,
    handleFolderMenuClick,
    handleRetryFile,
    fileMenuItems,
    handleFileMenuClick,
    getBreadcrumbDropProps,
    handleSaveFileMetadata,
    handleSaveBatchFileMetadata,
    handleDeleteBatchFileMetadata,
    handleSaveBatchFileTags,
  };
};
