// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { Alert, Button, Input, Table, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  FolderOpenOutlined,
  ReloadOutlined,
  SearchOutlined,
  TagsOutlined,
  UploadOutlined,
} from "@ant-design/icons";

import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import AidpImportDrawer from "@/ext_components/aidp/features/file-import/AidpImportDrawer";
import AidpFileMetadataDrawer from "@/ext_components/aidp/pages/knowledge-files/AidpFileMetadataDrawer";
import AidpBatchMetadataDrawer from "@/ext_components/aidp/pages/knowledge-files/AidpBatchMetadataDrawer";
import AidpResizableTitle from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import AidpFolderTree from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderTree";
import AidpFolderNameModal from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderNameModal";
import AidpFolderPickerModal from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderPickerModal";
import AidpFilesEmptyState from "@/ext_components/aidp/pages/knowledge-files/components/AidpFilesEmptyState";
import panelStyles from "@/ext_components/aidp/pages/knowledge-files/components/AidpKnowledgeFilesPanel.module.css";
import {
  folderTreeStatusMeta,
  sumColumnWidths,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";
import { parentFolderPath } from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFolderUtils";
import {
  FILE_COLUMN_MIN_WIDTHS,
  toDocumentItem,
  type AidpKnowledgeFilesPanelProps,
  type FileTableRecord,
} from "./AidpKnowledgeFilesPanel.types";
import { useAidpFilesPanelState } from "../hooks/useAidpFilesPanelState";
import { useAidpFileActions } from "../hooks/useAidpFileActions";
import { useAidpFileMenus } from "../hooks/useAidpFileMenus";

const AidpKnowledgeFilesPanel: React.FC<AidpKnowledgeFilesPanelProps> = (
  props
) => {
  const { t } = useTranslation();
  const { knowledgeBase, canEdit, isAvailable, onOpenFile } = props;
  const state = useAidpFilesPanelState(props);
  const actions = useAidpFileActions(state, knowledgeBase, canEdit);
  const menus = useAidpFileMenus(
    state,
    actions,
    knowledgeBase,
    canEdit,
    onOpenFile
  );
  const {
    i18n,
    message,
    modal,
    currentPath,
    setCurrentPath,
    globalKeywordInput,
    setGlobalKeywordInput,
    globalKeyword,
    folderKeywordInput,
    setFolderKeywordInput,
    folderKeyword,
    folderSearchOpen,
    setFolderSearchOpen,
    pageParams,
    setPageParams,
    searchPageParams,
    setSearchPageParams,
    selectedFileKeys,
    setSelectedFileKeys,
    columnWidths,
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
    deleteConfirmOpen,
    setDeleteConfirmOpen,
    metadataFile,
    setMetadataFile,
    batchMetadataFiles,
    setBatchMetadataFiles,
    metadataSubmitting,
    setMetadataSubmitting,
    odId,
    metadataFields,
    moveFailures,
    setMoveFailures,
    deleteFailures,
    setDeleteFailures,
    movingFileUuids,
    dragOverFolderKey,
    breadcrumbDropPath,
    displayedFiles,
    displayedTotal,
    searchQuery,
    fileTotal,
    displayedLoading,
    displayedError,
    globalSearchActive,
    refreshAll,
    openFolder,
    openImport,
    rows,
    showEmptyState,
    selectedFileUuids,
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
    handleDeleteFile,
    handleBatchDeleteFiles,
    handleDeleteFolder,
    submitFolderName,
    handleMoveFolder,
    handleMoveFile,
    handleRenameFile,
  } = actions;
  const {
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
  } = menus;

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
          {canEdit && odId !== null && (
            <Button
              icon={<TagsOutlined />}
              disabled={selectedFileUuids.length === 0}
              onClick={() => {
                const selectedFiles = displayedFiles.filter(
                  (file) =>
                    Boolean(file.file_uuid) &&
                    selectedFileKeys.includes(`file:${file.file_uuid}`)
                );
                if (selectedFiles.length !== selectedFileKeys.length) {
                  message.warning(
                    t("aidpKnowledge.batchMetadataUnavailable")
                  );
                  return;
                }
                if (selectedFiles.length > 100) {
                  message.warning(
                    t("aidpKnowledge.batchMetadataFileLimit", { max: 100 })
                  );
                  return;
                }
                setBatchMetadataFiles(selectedFiles.map(toDocumentItem));
              }}
            >
              {t("aidpKnowledge.batchMetadataTitle")}
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

      {deleteFailures && (
        <Alert
          type={deleteFailures.successCount > 0 ? "warning" : "error"}
          showIcon
          closable
          onClose={() => setDeleteFailures(null)}
          className="mb-4"
          title={t("aidpKnowledge.deleteFilesResultTitle", {
            success: deleteFailures.successCount,
            failed: deleteFailures.failedCount,
          })}
          description={
            <ul className="max-h-40 overflow-auto">
              {deleteFailures.items.map((item) => (
                <li key={item.fileUuid}>
                  <span className="font-medium">{item.fileName}</span>
                  {"："}
                  {item.reason}
                </li>
              ))}
            </ul>
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
        errorMessage={folderNameError}
        onCancel={() => {
          setFolderNameDialog(null);
          setFolderNameError(null);
        }}
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

      <AidpFileMetadataDrawer
        open={metadataFile !== null}
        fileName={metadataFile?.file_name ?? ""}
        odId={odId}
        metadataFields={metadataFields}
        submitting={metadataSubmitting}
        onClose={() => {
          if (!metadataSubmitting) setMetadataFile(null);
        }}
        onSave={handleSaveFileMetadata}
      />

      <AidpBatchMetadataDrawer
        open={batchMetadataFiles !== null}
        files={(batchMetadataFiles ?? []).map((file) => ({
          name: file.file_name,
          type: file.file_type,
        }))}
        metadataFields={metadataFields}
        submitting={metadataSubmitting}
        formKey={`files:${(batchMetadataFiles ?? [])
          .map((file) => file.file_uuid)
          .join(",")}:${odId ?? "none"}`}
        onClose={() => {
          if (!metadataSubmitting) setBatchMetadataFiles(null);
        }}
        onSave={handleSaveBatchFileMetadata}
      />
    </section>
  );
};

export default AidpKnowledgeFilesPanel;
