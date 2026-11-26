// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";

import { Button, Modal } from "antd";
import HighFidelityTextArea from "./HighFidelityTextArea";

interface HighFidelityPromptEditModalProps {
  title: string;
  content: string;
  readOnly: boolean;
  onClose: () => void;
  onChange: (content: string) => void;
}

export default function HighFidelityPromptEditModal({
  title,
  content,
  readOnly,
  onClose,
  onChange,
}: HighFidelityPromptEditModalProps) {
  const { t } = useTranslation("common");

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
      onCancel={onClose}
      footer={
        <Button type="primary" onClick={onClose}>
          {t("common.done")}
        </Button>
      }
    >
      <HighFidelityTextArea
        limit={100000}
        value={content}
        onChange={(event) => onChange(event.target.value)}
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
