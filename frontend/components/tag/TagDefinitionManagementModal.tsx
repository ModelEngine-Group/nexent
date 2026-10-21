// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import TagDefinitionManagementPanel from "./TagDefinitionManagementPanel";

interface TagDefinitionManagementModalProps {
  open: boolean;
  onClose: () => void;
  bucketId: number;
  bucketName: string;
  canManage: boolean;
}

export default function TagDefinitionManagementModal({
  open,
  onClose,
  bucketId,
  bucketName,
  canManage,
}: TagDefinitionManagementModalProps) {
  const { t } = useTranslation("common");
  return (
    <Modal
      title={`${t("tagManagement.title.definitionManagement")} - ${bucketName}`}
      open={open}
      onCancel={onClose}
      footer={null}
      width={1100}
      zIndex={1200}
      centered
      destroyOnHidden
    >
      {open && (
        <TagDefinitionManagementPanel
          key={bucketId}
          bucketId={bucketId}
          canManage={canManage}
        />
      )}
    </Modal>
  );
}
