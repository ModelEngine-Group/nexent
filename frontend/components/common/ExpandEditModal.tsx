// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/common/Modal";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/common/Button";

export interface ExpandEditModalProps {
  open: boolean;
  title: string;
  content: string;
  onClose: () => void;
  onSave: (content: string) => void;
  readOnly?: boolean;
}

export default function ExpandEditModal({
  open,
  title,
  content,
  onClose,
  onSave,
  readOnly = false,
}: ExpandEditModalProps) {
  const { t } = useTranslation("common");
  const [editContent, setEditContent] = useState(content);

  // Update editContent when content prop changes
  useEffect(() => {
    setEditContent(content);
  }, [content]);

  const handleSave = () => {
    if (!readOnly) {
      onSave(editContent);
    }
    onClose();
  };

  const handleClose = () => {
    // Close without saving changes
    onClose();
  };
  return (
    <Modal
      title={
        <div className="flex justify-between items-center">
          <div className="flex items-center">
            <span className="text-base font-medium">{title}</span>
          </div>
        </div>
      }
      open={open}
      onClose={handleClose}
      closeLabel={t("common.close")}
      footer={
        readOnly ? (
          <Button onClick={handleClose}>{t("common.close")}</Button>
        ) : (
          <div className="flex gap-2">
            <Button onClick={handleClose}>{t("common.cancel")}</Button>
            <Button variant="default" onClick={handleSave}>
              {t("common.confirm")}
            </Button>
          </div>
        )
      }
      width={1000}
      bodyClassName="p-1"
    >
      <div>
        <div className="flex-1 min-h-0">
          <Textarea
            value={editContent}
            onChange={(e) => {
              if (!readOnly) {
                setEditContent(e.target.value);
              }
            }}
            style={{
              width: "100%",
              minHeight: "400px",
              resize: "vertical",
            }}
            readOnly={readOnly}
          />
        </div>
      </div>
    </Modal>
  );
}
