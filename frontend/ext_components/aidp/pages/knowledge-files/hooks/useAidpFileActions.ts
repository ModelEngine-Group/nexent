// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback } from "react";
import { useConfirmModal } from "@/ext_components/aidp/shared/hooks/useConfirmModal";
import { useMutation } from "@tanstack/react-query";

import type { AidpFolderFileItem } from "@/ext_components/aidp/shared/types/management";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import {
  getAidpErrorMessage,
  isAidpNameConflictError,
} from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { getAidpDownloadFilename } from "@/ext_components/aidp/shared/utils/aidpDownloadFilename";
import { ApiError } from "@/services/api";
import log from "@/lib/logger";
import type { AidpFolderNodeTarget } from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderTree";
import {
  joinFolderPath,
  parentFolderPath,
  replaceFolderPrefix,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFolderUtils";
import {
  hasAidpFileMoveDrag,
  readAidpFileMoveDrag,
  setAidpFileMoveDragImage,
  writeAidpFileMoveDrag,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFileDrag";
import {
  AIDP_BATCH_DELETE_MAX,
  localizedFailureReason,
  type AidpKnowledgeFilesPanelProps,
  type FileTableRecord,
} from "../components/AidpKnowledgeFilesPanel.types";
import type { AidpFilesPanelState } from "./useAidpFilesPanelState";

export const useAidpFileActions = (
  state: AidpFilesPanelState,
  knowledgeBase: AidpKnowledgeFilesPanelProps["knowledgeBase"],
  canEdit: boolean
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
    metadataSubmitting,
    setMetadataSubmitting,
    bindingQuery,
    odId,
    metadataSchemaQuery,
    metadataFields,
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

  const confirm = useConfirmModal();

  const moveFilesMutation = useMutation({
    mutationFn: ({
      fileUuids,
      targetFolder,
    }: {
      fileUuids: string[];
      targetFolder: string;
    }) =>
      aidpKnowledgeService.moveFiles(
        knowledgeBase.kds_id,
        fileUuids,
        targetFolder
      ),
  });
  const deleteFileMutation = useMutation({
    mutationFn: (fileUuid: string) =>
      aidpKnowledgeService.removeDoc(knowledgeBase.kds_id, fileUuid),
  });
  const deleteFilesMutation = useMutation({
    mutationFn: (fileUuids: string[]) =>
      aidpKnowledgeService.removeDocs(knowledgeBase.kds_id, fileUuids),
  });
  const deleteFolderMutation = useMutation({
    mutationFn: (folderPath: string) =>
      aidpKnowledgeService.deleteFolder(knowledgeBase.kds_id, folderPath),
  });
  const createFolderMutation = useMutation({
    mutationFn: ({
      parentPath,
      name,
    }: {
      parentPath: string;
      name: string;
    }) =>
      aidpKnowledgeService.createFolder(
        knowledgeBase.kds_id,
        parentPath,
        name
      ),
  });
  const renameFolderMutation = useMutation({
    mutationFn: ({
      parentPath,
      name,
      newName,
    }: {
      parentPath: string;
      name: string;
      newName: string;
    }) =>
      aidpKnowledgeService.renameFolder(
        knowledgeBase.kds_id,
        parentPath,
        name,
        newName
      ),
  });
  const moveFolderMutation = useMutation({
    mutationFn: ({
      parentPath,
      name,
      targetFolder,
      mergeOnConflict,
    }: {
      parentPath: string;
      name: string;
      targetFolder: string;
      mergeOnConflict: boolean;
    }) =>
      aidpKnowledgeService.moveFolder(
        knowledgeBase.kds_id,
        parentPath,
        name,
        targetFolder,
        mergeOnConflict
      ),
  });
  const renameFileMutation = useMutation({
    mutationFn: ({ fileUuid, name }: { fileUuid: string; name: string }) =>
      aidpKnowledgeService.renameFile(
        knowledgeBase.kds_id,
        fileUuid,
        name
      ),
  });

  const performFileMove = useCallback(
    async (fileUuids: string[], targetFolder: string) => {
      if (fileUuids.length === 0) return;
      if (!globalSearchActive && targetFolder === currentPath) {
        message.info(t("aidpKnowledge.fileMoveSameFolder"));
        return;
      }
      setMoveFailures(null);
      setMovingFileUuids(fileUuids);
      try {
        const result = await moveFilesMutation.mutateAsync({
          fileUuids,
          targetFolder,
        });
        const failedItems = (result.failed_list ?? []).map((item) => {
          const reason = localizedFailureReason(
            item,
            i18n.language,
            t("aidpKnowledge.fileMoveFailed")
          );
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
      globalSearchActive,
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

  const stepBackIfPageEmptied = useCallback(
    (deletedCount: number) => {
      if (deletedCount <= 0 || deletedCount < displayedFiles.length) return;
      if (globalSearchActive) {
        setSearchPageParams((current) =>
          current.page > 1 ? { ...current, page: current.page - 1 } : current
        );
      } else {
        setPageParams((current) =>
          current.page > 1 ? { ...current, page: current.page - 1 } : current
        );
      }
    },
    [displayedFiles.length, globalSearchActive]
  );

  const handleDeleteFile = useCallback(
    (file: AidpFolderFileItem) => {
      if (!file.file_uuid) return;
      setDeleteConfirmOpen(true);
      void Promise.resolve(
        confirm({
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
              const result = await deleteFileMutation.mutateAsync(
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
                const reason = localizedFailureReason(
                  failed,
                  i18n.language,
                  t("aidpKnowledge.deleteDocFailed")
                );
                const code = failed?.error_code ?? failed?.code;
                throw code ? new ApiError(code, reason) : new Error(reason);
              }
              message.success(t("aidpKnowledge.deleteDocSuccess"));
              setSelectedFileKeys((current) =>
                current.filter((key) => key !== `file:${file.file_uuid}`)
              );
              stepBackIfPageEmptied(1);
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
    [
      i18n.language,
      knowledgeBase.kds_id,
      message,
      modal,
      refreshAll,
      stepBackIfPageEmptied,
      t,
    ]
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
      confirm({
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
            const result = await deleteFilesMutation.mutateAsync(fileUuids);
            const { success, failed } = result.summary;
            const failedItems = (result.failed_list ?? []).map((item) => {
              const reason = localizedFailureReason(
                item,
                i18n.language,
                t("aidpKnowledge.deleteDocFailed")
              );
              return {
                fileUuid: item.file_uuid,
                fileName: fileNameByUuid.get(item.file_uuid) || item.file_uuid,
                reason,
              };
            });
            if (failed === 0) {
              message.success(t("aidpKnowledge.deleteDocSuccess"));
              setSelectedFileKeys([]);
              setDeleteFailures(null);
            } else {
              setDeleteFailures({
                successCount: success,
                failedCount: failed,
                items: failedItems,
              });
              setSelectedFileKeys(
                failedItems.map((item) => `file:${item.fileUuid}`)
              );
            }
            stepBackIfPageEmptied(success);
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
    fileNameByUuid,
    i18n.language,
    knowledgeBase.kds_id,
    message,
    modal,
    refreshAll,
    selectedDeletableUuids,
    selectedFileUuids,
    stepBackIfPageEmptied,
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
        confirm({
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
              await deleteFolderMutation.mutateAsync(target.path);
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
      setFolderNameError(null);
      try {
        if (folderNameDialog.mode === "create") {
          await createFolderMutation.mutateAsync({
            parentPath: folderNameDialog.parentPath,
            name,
          });
          message.success(t("aidpKnowledge.folderCreateSuccess"));
        } else {
          const { target } = folderNameDialog;
          const parent = parentFolderPath(target.path);
          const result = await renameFolderMutation.mutateAsync({
            parentPath: parent,
            name: target.name,
            newName: name,
          });
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
        setFolderNameError(null);
        refreshAll();
      } catch (error) {
        log.error("Failed to save AIDP folder name:", {
          id: knowledgeBase.kds_id,
          dialog: folderNameDialog,
          error,
        });
        const errorText = getAidpErrorMessage(
          error,
          t,
          t("aidpKnowledge.folderSaveFailed")
        );
        if (isAidpNameConflictError(error)) {
          setFolderNameError(errorText);
          return;
        }
        message.error(errorText);
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
        const result = await moveFolderMutation.mutateAsync({
          parentPath: parent,
          name: target.name,
          targetFolder,
          mergeOnConflict,
        });
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
          confirm({
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
        await renameFileMutation.mutateAsync({
          fileUuid: file.file_uuid,
          name,
        });
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


  return {
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
  };
};

export type AidpFileActions = ReturnType<typeof useAidpFileActions>;
