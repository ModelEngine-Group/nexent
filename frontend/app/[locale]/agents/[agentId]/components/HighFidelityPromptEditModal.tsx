"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { StandardModal } from "@/components/common/StandardModal";
import { StandardButton } from "@/components/common/StandardButton";
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
    <StandardModal
      open
      title={title}
      width={1000}
      closeLabel={t("common.close")}
      cancelText={t("common.cancel")}
      confirmText={t("common.confirm")}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      onConfirm={() => {
        if (readOnly) return false;
        onSave(editContent);
      }}
      footer={
        readOnly ? (
          <div className="flex justify-end">
            <StandardButton onClick={onClose}>
              {t("common.close")}
            </StandardButton>
          </div>
        ) : undefined
      }
    >
      <HighFidelityTextArea
        limit={1000}
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
    </StandardModal>
  );
}
