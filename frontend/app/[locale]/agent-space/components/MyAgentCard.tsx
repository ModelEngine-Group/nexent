"use client";

import { Button, Card, Dropdown } from "antd";
import type { MenuProps } from "antd";
import {
  Bot,
  ClipboardCheck,
  Clock,
  MoreHorizontal,
  Pencil,
  Share2,
  Store,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  formatMineDate,
  getMineCardMenuActions,
  pickLatestSharedVersionName,
  type MineCardMenuAction,
} from "@/lib/agentRepositoryMine";
import type { MyEditableAgentItem } from "@/types/agentRepository";

interface MyAgentCardProps {
  agent: MyEditableAgentItem;
  onEdit: () => void;
  onApplyListing: () => void;
  onViewReview: (mode: "review" | "reviewUpdate") => void;
  isApplying?: boolean;
}

const MENU_ACTION_I18N: Record<MineCardMenuAction, string> = {
  apply: "agentRepository.mine.menu.apply",
  review: "agentRepository.mine.menu.review",
  reviewUpdate: "agentRepository.mine.menu.reviewUpdate",
};

export function MyAgentCard({
  agent,
  onEdit,
  onApplyListing,
  onViewReview,
  isApplying = false,
}: MyAgentCardProps) {
  const { t } = useTranslation("common");

  const title = agent.name?.trim() || t("agentRepository.card.untitled");
  const description =
    agent.description?.trim() || t("agentRepository.card.noDescription");
  const published = (agent.current_version_no ?? 0) > 0;
  const repositoryInfo = agent.repository_info ?? [];
  const hasRepositoryInfo = repositoryInfo.length > 0;
  const hasShared = repositoryInfo.some((item) => item.status === "shared");
  const hasPendingReview = repositoryInfo.some(
    (item) => item.status === "pending_review"
  );
  const hasRejected = repositoryInfo.some((item) => item.status === "rejected");
  const onlineVersion = pickLatestSharedVersionName(repositoryInfo);
  const footerDate = formatMineDate(agent.version_create_time);
  const versionLabel = agent.version_label;
  const menuActions = getMineCardMenuActions(agent);

  const menuItems: MenuProps["items"] = menuActions.map((action) => {
    const icon =
      action === "apply" ? (
        <Share2 className="size-3.5" aria-hidden />
      ) : (
        <ClipboardCheck className="size-3.5" aria-hidden />
      );

    return {
      key: action,
      label: t(MENU_ACTION_I18N[action]),
      icon,
      disabled: action === "apply" && isApplying,
      onClick: () => {
        if (action === "apply") {
          onApplyListing();
          return;
        }
        onViewReview(action === "reviewUpdate" ? "reviewUpdate" : "review");
      },
    };
  });

  return (
    <Card
      className="h-full rounded-2xl border border-slate-200 shadow-sm dark:border-slate-700"
      styles={{
        body: {
          height: "100%",
          display: "flex",
          flexDirection: "column",
          padding: 20,
        },
      }}
    >
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Bot className="size-5" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <h3 className="truncate text-base font-semibold text-slate-900 dark:text-slate-100">
                {title}
              </h3>
              {hasRepositoryInfo ? (
                <span className="inline-flex items-center gap-0.5 rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                  <Share2 className="size-2.5" aria-hidden />
                  {t("agentRepository.mine.onHub")}
                </span>
              ) : null}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <span
                className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
                  published
                    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                    : "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                }`}
              >
                {published
                  ? t("agentRepository.mine.lifecycle.published")
                  : t("agentRepository.mine.lifecycle.draft")}
              </span>
              {hasShared ? (
                <span className="inline-flex items-center gap-0.5 rounded-md bg-sky-50 px-1.5 py-0.5 text-[11px] font-medium text-sky-700 dark:bg-sky-500/10 dark:text-sky-300">
                  <Store className="size-2.5" aria-hidden />
                  {t("agentRepository.mine.listed")}
                </span>
              ) : null}
              {onlineVersion ? (
                <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {t("agentRepository.mine.onlineVersion", { version: onlineVersion })}
                </span>
              ) : null}
              {hasPendingReview ? (
                <span className="rounded-md bg-orange-50 px-1.5 py-0.5 text-[11px] font-medium text-orange-700 dark:bg-orange-500/10 dark:text-orange-300">
                  {t("agentRepository.mine.updateReviewing")}
                </span>
              ) : null}
              {!hasPendingReview && hasRejected ? (
                <span className="rounded-md bg-red-50 px-1.5 py-0.5 text-[11px] font-medium text-red-700 dark:bg-red-500/10 dark:text-red-300">
                  {t("agentRepository.detail.status.rejected")}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        {menuActions.length > 0 ? (
          <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
            <Button
              type="text"
              size="small"
              className="size-8 shrink-0 text-slate-400 hover:text-slate-600"
              icon={<MoreHorizontal className="size-4" aria-hidden />}
              aria-label={t("agentRepository.mine.menu.more")}
            />
          </Dropdown>
        ) : null}
      </div>

      <p className="mt-3 line-clamp-2 min-h-[2.75rem] text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        {description}
      </p>

      <div className="mt-auto flex flex-col gap-3">
        <div className="flex min-h-[1.75rem] items-center gap-4 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
          {versionLabel != null ? (
            <span className="inline-flex items-center gap-1.5">
              <span className="size-1.5 rounded-full bg-primary" aria-hidden />
              {versionLabel}
            </span>
          ) : null}
          {footerDate ? (
            <span className="inline-flex items-center gap-1">
              <Clock className="size-3.5" aria-hidden />
              {footerDate}
            </span>
          ) : null}
        </div>

        <Button
          type="default"
          className="w-full"
          icon={<Pencil className="size-3.5" aria-hidden />}
          onClick={onEdit}
        >
          {t("agentRepository.mine.edit")}
        </Button>
      </div>
    </Card>
  );
}
