"use client";

import { useEffect, useState } from "react";
import { Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { AgentRepositoryListingItem } from "@/types/agentRepository";

export type AgentRepositoryReviewAction = "approve" | "reject";

interface AgentRepositoryReviewConfirmModalProps {
  open: boolean;
  action: AgentRepositoryReviewAction | null;
  listing: AgentRepositoryListingItem | null;
  loading?: boolean;
  onClose: () => void;
  onConfirm: (content?: string) => Promise<void>;
}

function getListingTitle(listing: AgentRepositoryListingItem) {
  return listing.display_name?.trim() || listing.name?.trim() || "";
}

export function AgentRepositoryReviewConfirmModal({
  open,
  action,
  listing,
  loading = false,
  onClose,
  onConfirm,
}: AgentRepositoryReviewConfirmModalProps) {
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
    getListingTitle(listing) || t("agentRepository.card.untitled");

  const handleOk = async () => {
    const trimmed = reviewOpinion.trim();
    await onConfirm(trimmed || undefined);
  };

  return (
    <Modal
      open={open}
      title={
        isApprove
          ? t("agentRepository.review.confirmApproveTitle")
          : t("agentRepository.review.confirmRejectTitle")
      }
      onCancel={onClose}
      onOk={handleOk}
      okText={
        isApprove
          ? t("agentRepository.review.approve")
          : t("agentRepository.review.reject")
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
            ? t("agentRepository.review.confirmApproveContent", { name: title })
            : t("agentRepository.review.confirmRejectContent", { name: title })}
        </p>
        <div className="space-y-2">
          <label
            htmlFor="agent-repository-review-opinion"
            className="block text-sm font-medium text-slate-700 dark:text-slate-200"
          >
            {t("agentRepository.review.reviewOpinionLabel")}
          </label>
          <Input.TextArea
            id="agent-repository-review-opinion"
            value={reviewOpinion}
            onChange={(event) => setReviewOpinion(event.target.value)}
            placeholder={t("agentRepository.review.reviewOpinionPlaceholder")}
            rows={4}
            disabled={loading}
          />
        </div>
      </div>
    </Modal>
  );
}
