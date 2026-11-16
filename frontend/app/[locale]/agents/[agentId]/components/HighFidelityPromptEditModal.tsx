// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Modal } from "antd";
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
      centered
      closable={{ "aria-label": t("common.close") }}
      styles={{
        body: { maxHeight: "50vh", overflowY: "auto", paddingBlock: 16 },
      }}
      cancelText={t("common.cancel")}
      okText={t("common.confirm")}
      onCancel={onClose}
      onOk={() => {
        if (readOnly) return;
        onSave(editContent);
        onClose();
      }}
      footer={
        readOnly ? (
          <div className="flex justify-end">
            <Button onClick={onClose}>{t("common.close")}</Button>
          </div>
        ) : undefined
      }
    >
      <HighFidelityTextArea
        limit={100000}
        value={editContent}
        onChange={(event) => setEditContent(event.target.value)}
        disabled={readOnly}
        aria-label={title}
        classNames={{
          textarea:
            "!min-h-[400px] !rounded-[4px] !border-[#c9c9c9] !px-3 !py-2 !text-sm !leading-[22px]",
          count: "!bottom-2 !right-3 !text-xs !leading-[22px] !text-[#808080]",
        }}
      />
    </Modal>
  );
}
