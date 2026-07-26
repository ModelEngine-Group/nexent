"use client";

import { Button, Modal } from "antd";
import { CheckCircle2, Clock, Store, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { isCancelableReviewStatus, isTakeDownableReviewStatus, formatMineDate } from "@/lib/mcpToolsMine";
import type { CommunityMcpCard } from "@/types/mcpTools";
import type { MineMcpCardItem } from "./MineMcpServiceCard";

interface MineMcpReviewStatusModalProps {
  open: boolean;
  item: MineMcpCardItem | null;
  onlineService?: CommunityMcpCard;
  isUpdatingStatus?: boolean;
  onClose: () => void;
  onCancelApply: (item: MineMcpCardItem, onlineService?: CommunityMcpCard) => Promise<void>;
  onTakeDown: (item: MineMcpCardItem, onlineService: CommunityMcpCard) => Promise<void>;
}

export default function MineMcpReviewStatusModal({
  open,
  item,
  onlineService,
  isUpdatingStatus = false,
  onClose,
  onCancelApply,
  onTakeDown,
}: MineMcpReviewStatusModalProps) {
  const { t } = useTranslation("common");

  if (!item) return null;

  const service = item.service;
  const title = service.name?.trim() || "-";
  const communityRecord = item.kind === "community" ? item.service : onlineService;
  const reviewStatus = communityRecord?.reviewStatus || "pending";
  const isPending = reviewStatus === "pending";
  const isRejected = reviewStatus === "rejected";
  const canCancel = isCancelableReviewStatus(reviewStatus);
  const canTakeDown = isTakeDownableReviewStatus(reviewStatus);
  const submittedAt = formatMineDate(communityRecord?.createdAt);

  const statusConfig = isPending
    ? {
        icon: Clock,
        label: t("mcpTools.mine.reviewModal.pendingLabel"),
        description: t("mcpTools.mine.reviewModal.pendingDescription"),
        tone:
          "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200",
        iconClass: "text-amber-600 dark:text-amber-300",
      }
    : isRejected
      ? {
          icon: XCircle,
          label: t("mcpTools.mine.reviewModal.rejectedLabel"),
          description: t("mcpTools.mine.reviewModal.rejectedDescription"),
          tone:
            "border-red-200 bg-red-50 text-red-800 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200",
          iconClass: "text-red-600 dark:text-red-300",
        }
      : {
          icon: CheckCircle2,
          label: t("mcpTools.mine.reviewModal.approvedLabel"),
          description: t("mcpTools.mine.reviewModal.approvedDescription"),
          tone:
            "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200",
          iconClass: "text-emerald-600 dark:text-emerald-300",
        };

  const StatusIcon = statusConfig.icon;

  const confirmCancelApply = () => {
    Modal.confirm({
      title: t("mcpTools.mine.reviewModal.confirmCancelApplyTitle"),
      content: t("mcpTools.mine.reviewModal.confirmCancelApplyContent", {
        name: title,
      }),
      okText: t("mcpTools.mine.reviewModal.cancelApply"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        try {
          await onCancelApply(item, onlineService);
        } catch {
          throw new Error("Cancel listing request failed");
        }
      },
    });
  };

  const confirmTakeDown = () => {
    Modal.confirm({
      title: t("mcpTools.mine.reviewModal.confirmTakeDownTitle"),
      content: t("mcpTools.mine.reviewModal.confirmTakeDownContent", {
        name: title,
      }),
      okText: t("mcpTools.mine.reviewModal.takeDown"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        try {
          if (onlineService) await onTakeDown(item, onlineService);
        } catch {
          throw new Error("Take down failed");
        }
      },
    });
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button onClick={onClose} disabled={isUpdatingStatus}>
            {t("common.close")}
          </Button>
          {canCancel ? (
            <Button
              danger
              loading={isUpdatingStatus}
              icon={<XCircle className="size-4" aria-hidden />}
              onClick={confirmCancelApply}
            >
              {t("mcpTools.mine.reviewModal.cancelApply")}
            </Button>
          ) : null}
          {canTakeDown ? (
            <Button
              danger
              loading={isUpdatingStatus}
              icon={<XCircle className="size-4" aria-hidden />}
              onClick={confirmTakeDown}
            >
              {t("mcpTools.mine.reviewModal.takeDown")}
            </Button>
          ) : null}
        </div>
      }
      title={
        <span className="inline-flex items-center gap-2">
          <Store className="size-5 text-primary" aria-hidden />
          {t("mcpTools.mine.reviewModal.title")}
        </span>
      }
      centered
      destroyOnHidden
    >
      <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        {t("mcpTools.mine.reviewModal.serviceName", { name: title })}
      </p>

      <div
        className={`mb-4 flex items-start gap-3 rounded-xl border p-4 ${statusConfig.tone}`}
      >
        <StatusIcon
          className={`mt-0.5 size-5 shrink-0 ${statusConfig.iconClass}`}
          aria-hidden
        />
        <div className="space-y-1">
          <p className="text-sm font-semibold">{statusConfig.label}</p>
          <p className="text-sm leading-relaxed opacity-90">
            {statusConfig.description}
          </p>
        </div>
      </div>

      {submittedAt ? (
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
          <div className="flex justify-between gap-4">
            <span>{t("mcpTools.mine.reviewModal.submittedAt")}</span>
            <span className="font-medium text-slate-700 dark:text-slate-200">
              {submittedAt}
            </span>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
