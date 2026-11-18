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
  initialPath?: string;
  /** A folder that cannot be selected (and whose subtree is invalid). */
  invalidPrefix?: string;
  invalidHint?: string;
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
  invalidPrefix,
  invalidHint,
  confirmText,
  onCancel,
  onSelect,
}) => {
  const { t } = useTranslation();
  const [selectedPath, setSelectedPath] = useState(
    normalizeFolderPath(initialPath)
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Each opening starts at the caller's current folder.
    if (open) setSelectedPath(normalizeFolderPath(initialPath));
  }, [initialPath, open]);

  const invalid = invalidPrefix
    ? isPathEqualOrInside(selectedPath, invalidPrefix)
    : false;

  return (
    <Modal
      open={open}
      title={title}
      centered
      width={520}
      okText={confirmText || t("common.confirm")}
      cancelText={t("common.cancel")}
      okButtonProps={{ disabled: invalid }}
      onCancel={onCancel}
      onOk={() => onSelect(selectedPath)}
      destroyOnHidden
    >
      <div className="flex flex-col gap-2">
        <Input
          readOnly
          value={selectedPath}
          aria-label={t("aidpKnowledge.uploadTargetLabel")}
        />
        {invalid && invalidHint && (
          <div className="text-xs text-red-500">{invalidHint}</div>
        )}
        <div className="h-[320px] overflow-auto rounded border border-gray-200 px-2">
          <AidpFolderTree
            knowledgeBaseId={knowledgeBaseId}
            rootLabel={rootLabel}
            selectedPath={selectedPath}
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
