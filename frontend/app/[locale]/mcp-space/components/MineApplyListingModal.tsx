"use client";

import { useEffect, useState } from "react";
import { Input, Modal } from "antd";
import { useTranslation } from "react-i18next";

import type { MineMcpCardItem } from "./MineMcpServiceCard";

interface MineApplyListingModalProps {
  open: boolean;
  item: MineMcpCardItem | null;
  loading?: boolean;
  onClose: () => void;
  onConfirm: (content?: string) => Promise<void>;
}

export default function MineApplyListingModal({
  open,
  item,
  loading = false,
  onClose,
  onConfirm,
}: MineApplyListingModalProps) {
  const { t } = useTranslation("common");
  const [listingContent, setListingContent] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      setListingContent("");
      setSubmitting(false);
    }
  }, [open]);

  if (!item) {
    return null;
  }

  const title = item.service.name?.trim() || "-";
  const isBusy = loading || submitting;

  const handleOk = async () => {
    setSubmitting(true);
    try {
      await onConfirm(listingContent.trim() || undefined);
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={t("repository.mine.applyForListing")}
      onCancel={onClose}
      onOk={handleOk}
      okText={t("repository.mine.applyForListing")}
      cancelText={t("common.cancel")}
      confirmLoading={isBusy}
      centered
      destroyOnHidden
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {t("repository.mine.confirmApplyTitle", { name: title })}
        </p>
        <div className="space-y-2">
          <label
            htmlFor="mcp-repository-listing-note"
            className="block text-sm font-medium text-slate-700 dark:text-slate-200"
          >
            {t("repository.mine.applyModal.content")}
          </label>
          <Input.TextArea
            id="mcp-repository-listing-note"
            value={listingContent}
            onChange={(event) => setListingContent(event.target.value)}
            placeholder={t("repository.mine.applyModal.contentPlaceholder")}
            rows={4}
            disabled={isBusy}
          />
        </div>
      </div>
    </Modal>
  );
}
