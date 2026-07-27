"use client";

import { useEffect, useState } from "react";
import { Input, Modal } from "antd";
import { useTranslation } from "react-i18next";

import type { CommunityMcpCard } from "@/types/mcpTools";

export type McpRepositoryReviewAction = "approve" | "reject";

interface McpRepositoryReviewConfirmModalProps {
  open: boolean;
  action: McpRepositoryReviewAction | null;
  service: CommunityMcpCard | null;
  loading?: boolean;
  onClose: () => void;
  onConfirm: (content?: string) => Promise<void>;
}

export default function McpRepositoryReviewConfirmModal({
  open,
  action,
  service,
  loading = false,
  onClose,
  onConfirm,
}: McpRepositoryReviewConfirmModalProps) {
  const { t } = useTranslation("common");
  const [reviewOpinion, setReviewOpinion] = useState("");

  useEffect(() => {
    if (!open) {
      setReviewOpinion("");
    }
  }, [open]);

  if (!action || !service) {
    return null;
  }

  const isApprove = action === "approve";
  const title = service.name?.trim() || "-";

  const handleOk = async () => {
    const trimmed = reviewOpinion.trim();
    await onConfirm(trimmed || undefined);
  };

  return (
    <Modal
      open={open}
      title={
        isApprove
          ? t("repository.review.confirmApproveTitle")
          : t("repository.review.confirmRejectTitle")
      }
      onCancel={onClose}
      onOk={handleOk}
      okText={
        isApprove ? t("repository.review.approve") : t("repository.review.reject")
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
            ? t("repository.review.confirmApproveContent", { name: title })
            : t("repository.review.confirmRejectContent", { name: title })}
        </p>
        <div className="space-y-2">
          <label
            htmlFor="mcp-repository-review-opinion"
            className="block text-sm font-medium text-slate-700 dark:text-slate-200"
          >
            {t("repository.review.reviewOpinionLabel")}
          </label>
          <Input.TextArea
            id="mcp-repository-review-opinion"
            value={reviewOpinion}
            onChange={(event) => setReviewOpinion(event.target.value)}
            placeholder={t("repository.review.reviewOpinionPlaceholder")}
            rows={4}
            disabled={loading}
          />
        </div>
      </div>
    </Modal>
  );
}
