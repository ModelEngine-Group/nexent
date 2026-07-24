"use client";

import { useEffect, useState } from "react";
import { Input, Modal } from "antd";
import { useTranslation } from "react-i18next";

import type {
  MyEditableSkillItem,
  SkillRepositoryListingCreatePayload,
} from "@/types/skillRepository";

interface MineApplyListingModalProps {
  open: boolean;
  skill: MyEditableSkillItem | null;
  loading?: boolean;
  onClose: () => void;
  onConfirm: (payload: SkillRepositoryListingCreatePayload) => Promise<void>;
}

export function MineApplyListingModal({
  open,
  skill,
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

  if (!skill) {
    return null;
  }

  const title = skill.name?.trim() || t("skillRepository.common.untitled");
  const isBusy = loading || submitting;

  const handleOk = async () => {
    setSubmitting(true);
    try {
      await onConfirm({
        icon: "skill",
        tags: skill.tags ?? [],
        content: listingContent.trim() || undefined,
      });
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={t("skillRepository.mine.confirmApplyTitle", { name: title })}
      onCancel={onClose}
      onOk={handleOk}
      okText={t("skillRepository.mine.submitReview")}
      cancelText={t("common.cancel")}
      confirmLoading={isBusy}
      centered
      destroyOnHidden
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {t("skillRepository.mine.confirmApplyContent")}
        </p>
        <div className="space-y-2">
          <label
            htmlFor="skill-repository-listing-note"
            className="block text-sm font-medium text-slate-700 dark:text-slate-200"
          >
            {t("skillRepository.mine.applyModal.content")}
          </label>
          <Input.TextArea
            id="skill-repository-listing-note"
            value={listingContent}
            onChange={(event) => setListingContent(event.target.value)}
            placeholder={t(
              "skillRepository.mine.applyModal.contentPlaceholder"
            )}
            rows={4}
            disabled={isBusy}
          />
        </div>
      </div>
    </Modal>
  );
}
