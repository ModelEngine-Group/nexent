// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Input, Modal } from "antd";

import AidpFolderTree from "@/ext_components/aidp/pages/knowledge-files/components/AidpFolderTree";
import {
  isPathEqualOrInside,
  normalizeFolderPath,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFolderUtils";

interface AidpFolderPickerModalProps {
  open: boolean;
  knowledgeBaseId: string;
  rootLabel: string;
  title: string;
  /** Folder to reveal when the dialog opens; not necessarily preselected. */
  initialPath?: string;
  /** Preselect initialPath. Move dialogs pass false so no destination is implied. */
  preselect?: boolean;
  /** A folder that cannot be selected (and whose subtree is invalid). */
  invalidPrefix?: string;
  invalidHint?: string;
  /** A single folder that is not a useful destination (e.g. the current one). */
  disabledPath?: string;
  disabledHint?: string;
  confirmText?: string;
  onCancel: () => void;
  onSelect: (path: string) => void;
}

/**
 * Browse-only folder picker used by "upload to", file move and folder move.
 * It reuses the lazy tree so a knowledge base with deep folders never needs a
 * full-tree request.
 */
const AidpFolderPickerModal: React.FC<AidpFolderPickerModalProps> = ({
  open,
  knowledgeBaseId,
  rootLabel,
  title,
  initialPath = "/",
  preselect = true,
  invalidPrefix,
  invalidHint,
  disabledPath,
  disabledHint,
  confirmText,
  onCancel,
  onSelect,
}) => {
  const { t } = useTranslation();
  const startPath = normalizeFolderPath(initialPath);
  const [selectedPath, setSelectedPath] = useState(preselect ? startPath : "");

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Each opening starts at the caller's current folder.
    if (open) setSelectedPath(preselect ? startPath : "");
  }, [open, preselect, startPath]);

  const outOfScope = Boolean(
    selectedPath &&
    invalidPrefix &&
    isPathEqualOrInside(selectedPath, invalidPrefix)
  );
  const sameAsDisabled = Boolean(
    selectedPath &&
    disabledPath &&
    selectedPath === normalizeFolderPath(disabledPath)
  );
  const invalid = outOfScope || sameAsDisabled;
  const invalidMessage = outOfScope
    ? invalidHint
    : sameAsDisabled
      ? disabledHint
      : undefined;

  return (
    <Modal
      open={open}
      title={title}
      centered
      width={520}
      okText={confirmText || t("common.confirm")}
      cancelText={t("common.cancel")}
      okButtonProps={{ disabled: !selectedPath || invalid }}
      onCancel={onCancel}
      onOk={() => {
        if (selectedPath && !invalid) onSelect(selectedPath);
      }}
      destroyOnHidden
    >
      <div className="flex flex-col gap-2">
        <Input
          readOnly
          value={selectedPath}
          placeholder={t("aidpKnowledge.folderPickerPlaceholder")}
          aria-label={t("aidpKnowledge.uploadTargetLabel")}
        />
        {invalid && invalidMessage && (
          <div className="text-xs text-red-500">{invalidMessage}</div>
        )}
        <div className="h-[320px] overflow-auto rounded border border-gray-200 px-2">
          <AidpFolderTree
            knowledgeBaseId={knowledgeBaseId}
            rootLabel={rootLabel}
            selectedPath={selectedPath}
            expandPath={startPath}
            disabledPrefix={invalidPrefix}
            onSelect={(path) => {
              if (invalidPrefix && isPathEqualOrInside(path, invalidPrefix)) {
                return;
              }
              setSelectedPath(path);
            }}
          />
        </div>
      </div>
    </Modal>
  );
};

export default AidpFolderPickerModal;
