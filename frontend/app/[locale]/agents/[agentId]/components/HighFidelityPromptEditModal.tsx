// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import HighFidelityTextArea from "./HighFidelityTextArea";

interface HighFidelityPromptEditModalProps {
  title: string;
  content: string;
  readOnly: boolean;
  onClose: () => void;
  onSave: (content: string) => void;
}

export default function HighFidelityPromptEditModal({
  title,
  content,
  readOnly,
  onClose,
  onSave,
}: HighFidelityPromptEditModalProps) {
  const { t } = useTranslation("common");
  const [editContent, setEditContent] = useState(content);

  return (
    <Modal
      open
      title={title}
      width={1000}
      closeLabel={t("common.close")}
      footer={
        readOnly ? (
          <div className="flex justify-end">
            <Button onClick={onClose} variant="outline" size="sm">
              {t("common.close")}
            </Button>
          </div>
        ) : undefined
      }
      onClose={onClose}
      actions={{
        cancelLabel: t("common.cancel"),
        confirmLabel: t("common.confirm"),
        onConfirm: () => {
          if (readOnly) return;
          onSave(editContent);
          onClose();
        },
      }}
    >
      <HighFidelityTextArea
        limit={100000}
        value={editContent}
        onChange={(event) => setEditContent(event.target.value)}
        disabled={readOnly}
        aria-label={title}
        className="!min-h-[400px] !rounded-[4px] !border-[#c9c9c9] !px-3 !py-2 !text-sm !leading-[22px]"
        countClassName="absolute bottom-2 right-3 !text-xs !leading-[22px] !text-[#808080]"
      />
    </Modal>
  );
}
