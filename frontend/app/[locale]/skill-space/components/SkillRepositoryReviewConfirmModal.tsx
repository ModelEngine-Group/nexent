"use client";

import { useEffect, useState } from "react";
import { Input, Modal } from "antd";
import { useTranslation } from "react-i18next";

import type { SkillRepositoryListingItem } from "@/types/skillRepository";

export type SkillRepositoryReviewAction = "approve" | "reject";

interface SkillRepositoryReviewConfirmModalProps {
  open: boolean;
  action: SkillRepositoryReviewAction | null;
  listing: SkillRepositoryListingItem | null;
  loading?: boolean;
  onClose: () => void;
  onConfirm: (content?: string) => Promise<void>;
}

export function SkillRepositoryReviewConfirmModal({
  open,
  action,
  listing,
  loading = false,
  onClose,
  onConfirm,
}: SkillRepositoryReviewConfirmModalProps) {
  const { t } = useTranslation("common");
  const [reviewOpinion, setReviewOpinion] = useState("");

  useEffect(() => {
    if (!open) {
      setReviewOpinion("");
    }
  }, [open]);

  if (!action || !listing) {
    return null;
  }

  const isApprove = action === "approve";
  const title =
    listing.name?.trim() || t("skillRepository.common.untitled");

  const handleOk = async () => {
    const trimmed = reviewOpinion.trim();
    await onConfirm(trimmed || undefined);
  };

  return (
    <Modal
      open={open}
      title={
        isApprove
          ? t("skillRepository.review.confirmApproveTitle")
          : t("skillRepository.review.confirmRejectTitle")
      }
      onCancel={onClose}
      onOk={handleOk}
      okText={
        isApprove
          ? t("skillRepository.review.approve")
          : t("skillRepository.review.reject")
      }
      cancelText={t("common.cancel")}
      okButtonProps={isApprove ? undefined : { danger: true }}
      confirmLoading={loading}
      centered
      destroyOnHidden
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {isApprove
            ? t("skillRepository.review.confirmApproveContent", { name: title })
            : t("skillRepository.review.confirmRejectContent", { name: title })}
        </p>
        <div className="space-y-2">
          <label
            htmlFor="skill-repository-review-opinion"
            className="block text-sm font-medium text-slate-700 dark:text-slate-200"
          >
            {t("skillRepository.review.reviewOpinionLabel")}
          </label>
          <Input.TextArea
            id="skill-repository-review-opinion"
            value={reviewOpinion}
            onChange={(event) => setReviewOpinion(event.target.value)}
            placeholder={t("skillRepository.review.reviewOpinionPlaceholder")}
            rows={4}
            disabled={loading}
          />
        </div>
      </div>
    </Modal>
  );
}
