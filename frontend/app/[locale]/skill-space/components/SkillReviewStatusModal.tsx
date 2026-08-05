"use client";

import { Button, Modal } from "antd";
import { CheckCircle2, Clock, PackageX, Store, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  formatRepositoryDate,
  isCancelableRepositoryStatus,
  isTakeDownableRepositoryStatus,
} from "./skillRepositoryShared";
import type {
  MyEditableSkillItem,
  MySkillRepositoryInfoItem,
} from "@/types/skillRepository";

export function SkillReviewStatusModal({
  open,
  skill,
  repositoryInfo,
  isUpdatingStatus,
  onClose,
  onSetNotShared,
}: {
  open: boolean;
  skill: MyEditableSkillItem | null;
  repositoryInfo: MySkillRepositoryInfoItem | null;
  isUpdatingStatus: boolean;
  onClose: () => void;
  onSetNotShared: () => Promise<void>;
}) {
  const { t } = useTranslation("common");
  if (!skill || !repositoryInfo) return null;

  const title = skill.name?.trim() || `Skill #${skill.skill_id}`;
  const isPending = repositoryInfo.status === "pending_review";
  const isRejected = repositoryInfo.status === "rejected";
  const canCancelApply = isCancelableRepositoryStatus(repositoryInfo.status);
  const canTakeDown = isTakeDownableRepositoryStatus(repositoryInfo.status);
  const submittedAt = formatRepositoryDate(repositoryInfo.create_time);
  const listingContent = repositoryInfo.content?.trim() ?? "";

  const statusConfig = isPending
    ? {
        icon: Clock,
        label: t("repository.listingStatus.pendingLabel"),
        description: t("repository.listingStatus.pendingDescription"),
        tone: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200",
        iconClass: "text-amber-600 dark:text-amber-300",
      }
    : isRejected
      ? {
          icon: XCircle,
          label: t("repository.listingStatus.rejectedLabel"),
          description: t("repository.listingStatus.rejectedDescription"),
          tone: "border-red-200 bg-red-50 text-red-800 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200",
          iconClass: "text-red-600 dark:text-red-300",
        }
      : {
          icon: CheckCircle2,
          label: t("repository.listingStatus.listedLabel"),
          description: t("repository.listingStatus.listedDescription"),
          tone: "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200",
          iconClass: "text-emerald-600 dark:text-emerald-300",
        };

  const StatusIcon = statusConfig.icon;

  const confirmSetNotShared = () => {
    Modal.confirm({
      title: canTakeDown
        ? t("repository.listingStatus.confirmTakeDownTitle")
        : t("repository.listingStatus.confirmCancelApplyTitle"),
      content: canTakeDown
        ? t("repository.listingStatus.confirmTakeDownContent", {
            name: title,
          })
        : t("repository.listingStatus.confirmCancelApplyContent", {
            name: title,
          }),
      okText: canTakeDown
        ? t("repository.listingStatus.takeDown")
        : t("repository.listingStatus.cancelApply"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: onSetNotShared,
    });
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      centered
      destroyOnHidden
      title={
        <span className="inline-flex items-center gap-2">
          <Store className="size-5 text-primary" aria-hidden />
          {t("repository.listingStatus.title")}
        </span>
      }
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button onClick={onClose} disabled={isUpdatingStatus}>
            {t("common.close")}
          </Button>
          {canCancelApply || canTakeDown ? (
            <Button
              danger
              loading={isUpdatingStatus}
              icon={
                canTakeDown ? (
                  <PackageX className="size-4" aria-hidden />
                ) : (
                  <XCircle className="size-4" aria-hidden />
                )
              }
              onClick={confirmSetNotShared}
            >
              {canTakeDown
                ? t("repository.listingStatus.takeDown")
                : t("repository.listingStatus.cancelApply")}
            </Button>
          ) : null}
        </div>
      }
    >
      <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">{title}</p>

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
                ? t("repository.listingStatus.pendingNote", {
                    content: listingContent,
                  })
                : t("repository.listingStatus.reviewOpinion", {
                    content: listingContent,
                  })}
            </p>
          ) : null}
        </div>
      </div>

      {submittedAt ? (
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
          <div className="flex justify-between gap-4">
            <span>{t("repository.listingStatus.submittedAt")}</span>
            <span className="font-medium text-slate-700 dark:text-slate-200">
              {submittedAt}
            </span>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
