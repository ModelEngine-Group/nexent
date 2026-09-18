"use client";

import { Button, Dropdown } from "antd";
import type { MenuProps } from "antd";
import {
  Bot,
  ClipboardCheck,
  Clock,
  Eye,
  LineChart,
  MoreHorizontal,
  Pencil,
  Share2,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import {
  formatMineDate,
  getMineCardMenuActions,
  getMineCardRepositoryStatusBadge,
  type MineCardMenuAction,
} from "@/lib/agentRepositoryMine";
import type { MyEditableAgentItem } from "@/types/agentRepository";
import ResourceCard from "@/components/resource/ResourceCard";

interface MyAgentCardProps {
  agent: MyEditableAgentItem;
  onEdit: () => void;
  onView: () => void;
  onApplyListing: () => void;
  onViewReview: (mode: "review" | "reviewUpdate") => void;
  onDelete: () => void;
  onEvaluate: () => void;
  isApplying?: boolean;
  isDeleting?: boolean;
}

const MENU_ACTION_I18N: Record<MineCardMenuAction, string> = {
  apply: "agentRepository.mine.menu.apply",
  review: "agentRepository.mine.menu.review",
  reviewUpdate: "agentRepository.mine.menu.reviewUpdate",
};

const STATUS_BADGE_CLASS: Record<"pending" | "shared" | "rejected", string> = {
  pending:
    "bg-orange-50 text-orange-700 dark:bg-orange-500/10 dark:text-orange-300",
  shared: "bg-primary/10 text-primary dark:bg-primary/20 dark:text-primary",
  rejected: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300",
};

export function MyAgentCard({
  agent,
  onEdit,
  onView,
  onApplyListing,
  onViewReview,
  onDelete,
  onEvaluate,
  isApplying = false,
  isDeleting = false,
}: MyAgentCardProps) {
  const { t } = useTranslation("common");

  const title = agent.name?.trim() || t("agentRepository.card.untitled");
  const description =
    agent.description?.trim() || t("agentRepository.card.noDescription");
  const tags = agent.tags?.filter((tag) => tag.trim()) ?? [];
  const published = (agent.current_version_no ?? 0) > 0;
  const repositoryInfo = agent.repository_info ?? [];
  const repositoryStatusBadge =
    getMineCardRepositoryStatusBadge(repositoryInfo);
  const footerDate = formatMineDate(agent.version_create_time);
  const versionLabel = agent.version_label;
  const canEdit = agent.permission !== "READ_ONLY";
  const canView = (agent.current_version_no ?? 0) > 0;
  const canEvaluate = canView;
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

  if (canEvaluate) {
    menuItems.push({
      key: "evaluate",
      icon: <LineChart className="size-3.5" aria-hidden />,
      label: t("agentRepository.mine.evaluate"),
      onClick: onEvaluate,
    });
  }

  if (menuItems.length > 0 && canEdit) {
    menuItems.push({ type: "divider" });
  }

  if (canEdit) {
    menuItems.push({
      key: "delete",
      danger: true,
      icon: <Trash2 className="size-3.5" aria-hidden />,
      label: t("common.delete"),
      disabled: isDeleting,
      onClick: onDelete,
    });
  }

  return (
    <ResourceCard title={title} className="h-full">
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
              {repositoryStatusBadge ? (
                <span
                  className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${STATUS_BADGE_CLASS[repositoryStatusBadge.variant]}`}
                >
                  {t(repositoryStatusBadge.labelKey)}{" "}
                  {repositoryStatusBadge.versionLabel}
                </span>
              ) : null}
            </div>
            <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
              {versionLabel != null ? (
                <span className="inline-flex items-center gap-1.5 truncate">
                  <span
                    className="size-1.5 shrink-0 rounded-full bg-primary"
                    aria-hidden
                  />
                  {t("agentRepository.mine.currentVersion", {
                    version: versionLabel,
                  })}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {menuItems.length > 0 ? (
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
        </div>
      </div>

      <p className="mt-3 line-clamp-2 min-h-[2.75rem] text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        {description}
      </p>

      {tags.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {tags.map((tag) => (
            <span
              key={tag}
              className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
            >
              {getAgentRepositoryTagLabel(tag, t)}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-auto flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
        <div className="min-w-0">
          {footerDate ? (
            <span className="inline-flex items-center gap-1">
              <Clock className="size-3.5" aria-hidden />
              {footerDate}
            </span>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {canEdit ? (
            <Button
              type="text"
              size="small"
              className="h-8 px-3 text-xs font-medium text-primary !shadow-none hover:!bg-transparent hover:!text-primary/80"
              icon={<Pencil className="size-3.5" aria-hidden />}
              onClick={onEdit}
            >
              {t("agentRepository.mine.edit")}
            </Button>
          ) : (
            <Button
              type="text"
              size="small"
              className="h-8 px-3 text-xs font-medium text-primary !shadow-none hover:!bg-transparent hover:!text-primary/80"
              icon={<Eye className="size-3.5" aria-hidden />}
              onClick={onView}
              disabled={!canView}
            >
              {t("agentRepository.mine.view")}
            </Button>
          )}
        </div>
      </div>
    </ResourceCard>
  );
}
