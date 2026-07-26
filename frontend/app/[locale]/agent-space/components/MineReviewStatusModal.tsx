"use client";

import { Button, Modal } from "antd";
import { CheckCircle2, Clock, PackageX, Store, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  formatMineDate,
  formatRepositoryVersionLabel,
  isCancelableRepositoryStatus,
  isTakeDownableRepositoryStatus,
} from "@/lib/agentRepositoryMine";
import type {
  MyAgentRepositoryInfoItem,
  MyEditableAgentItem,
} from "@/types/agentRepository";

interface MineReviewStatusModalProps {
  open: boolean;
  agent: MyEditableAgentItem | null;
  repositoryInfo: MyAgentRepositoryInfoItem | null;
  mode: "review" | "reviewUpdate";
  isUpdatingStatus?: boolean;
  onClose: () => void;
  onSetNotShared: () => Promise<void>;
}

export function MineReviewStatusModal({
  open,
  agent,
  repositoryInfo,
  mode,
  isUpdatingStatus = false,
  onClose,
  onSetNotShared,
}: MineReviewStatusModalProps) {
  const { t } = useTranslation("common");

  if (!agent || !repositoryInfo) {
    return null;
  }

  const title = agent.name?.trim() || t("agentRepository.card.untitled");
  const isPending = repositoryInfo.status === "pending_review";
  const isRejected = repositoryInfo.status === "rejected";
  const canCancelApply = isCancelableRepositoryStatus(repositoryInfo.status);
  const canTakeDown = isTakeDownableRepositoryStatus(repositoryInfo.status);
  const versionLabel = formatRepositoryVersionLabel(repositoryInfo);
  const submittedAt = formatMineDate(repositoryInfo.create_time);
  const listingContent = repositoryInfo.content?.trim() ?? "";

  const statusConfig = isPending
    ? {
        icon: Clock,
        label: t("agentRepository.mine.reviewModal.pendingLabel"),
        description: t("agentRepository.mine.reviewModal.pendingDescription"),
        tone:
          "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200",
        iconClass: "text-amber-600 dark:text-amber-300",
      }
    : isRejected
      ? {
          icon: XCircle,
          label: t("agentRepository.mine.reviewModal.rejectedLabel"),
          description: t("agentRepository.mine.reviewModal.rejectedDescription"),
          tone:
            "border-red-200 bg-red-50 text-red-800 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200",
          iconClass: "text-red-600 dark:text-red-300",
        }
      : {
          icon: CheckCircle2,
          label: t("agentRepository.mine.reviewModal.sharedLabel"),
          description: t("agentRepository.mine.reviewModal.sharedDescription"),
          tone:
            "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200",
          iconClass: "text-emerald-600 dark:text-emerald-300",
        };

  const StatusIcon = statusConfig.icon;
  const modalTitle =
    mode === "reviewUpdate"
      ? t("agentRepository.mine.reviewModal.reviewUpdateTitle")
      : t("agentRepository.mine.reviewModal.title");

  const confirmCancelApply = () => {
    Modal.confirm({
      title: t("agentRepository.mine.reviewModal.confirmCancelApplyTitle"),
      content: t("agentRepository.mine.reviewModal.confirmCancelApplyContent", {
        name: title,
      }),
      okText: t("agentRepository.mine.reviewModal.cancelApply"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await onSetNotShared();
        } catch {
          throw new Error("Cancel listing request failed");
        }
      },
    });
  };

  const confirmTakeDown = () => {
    Modal.confirm({
      title: t("agentRepository.mine.reviewModal.confirmTakeDownTitle"),
      content: t("agentRepository.mine.reviewModal.confirmTakeDownContent", {
        name: title,
      }),
      okText: t("agentRepository.mine.reviewModal.takeDown"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await onSetNotShared();
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
          {canCancelApply ? (
            <Button
              danger
              loading={isUpdatingStatus}
              icon={<XCircle className="size-4" aria-hidden />}
              onClick={confirmCancelApply}
            >
              {t("agentRepository.mine.reviewModal.cancelApply")}
            </Button>
          ) : null}
          {canTakeDown ? (
            <Button
              danger
              loading={isUpdatingStatus}
              icon={<PackageX className="size-4" aria-hidden />}
              onClick={confirmTakeDown}
            >
              {t("agentRepository.mine.reviewModal.takeDown")}
            </Button>
          ) : null}
        </div>
      }
      title={
        <span className="inline-flex items-center gap-2">
          <Store className="size-5 text-primary" aria-hidden />
          {modalTitle}
        </span>
      }
      centered
      destroyOnHidden
    >
      <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        {t("agentRepository.mine.reviewModal.agentName", { name: title })}
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
          {listingContent ? (
            <p className="text-sm leading-relaxed opacity-90">
              {isPending
                ? t("agentRepository.mine.reviewModal.pendingNote", {
                    content: listingContent,
                  })
                : t("agentRepository.mine.reviewModal.reviewOpinion", {
                    content: listingContent,
                  })}
            </p>
          ) : null}
        </div>
      </div>

      <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
        <div className="flex justify-between gap-4">
          <span>{t("agentRepository.mine.reviewModal.version")}</span>
          <span className="font-medium text-slate-700 dark:text-slate-200">
            {versionLabel}
          </span>
        </div>
        {submittedAt ? (
          <div className="flex justify-between gap-4">
            <span>{t("agentRepository.mine.reviewModal.submittedAt")}</span>
            <span className="font-medium text-slate-700 dark:text-slate-200">
              {submittedAt}
            </span>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
