"use client";

import { Button, Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";
import {
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
import { getAgentUsageGuideAccess } from "@/lib/agentUsageGuide";
import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import { getUnavailableReasonLabels } from "@/lib/agentLabelMapper";
import {
  formatMineDate,
  getMineCardMenuActions,
  getMineCardRepositoryStatusBadge,
  type MineCardMenuAction,
} from "@/lib/agentRepositoryMine";
import type { MyEditableAgentItem } from "@/types/agentRepository";
import ResourceCard from "@/components/resource/ResourceCard";
import { MyAgentIcon } from "./MyAgentIcon";

interface MyAgentCardProps {
  agent: MyEditableAgentItem;
  onEdit: () => void;
  onView: () => void;
  onApplyListing: () => void;
  onViewReview: (
    agent: MyEditableAgentItem,
    mode: "review" | "reviewUpdate"
  ) => void;
  onDelete: () => void;
  onEvaluate: () => void;
  onUsageGuide: () => void;
  highlighted?: boolean;
  guideMenuOpen?: boolean;
  onGuideMenuOpenChange?: (open: boolean) => void;
  isApplying?: boolean;
  isDeleting?: boolean;
}

const MENU_ACTION_I18N: Record<MineCardMenuAction, string> = {
  apply: "agentRepository.mine.menu.apply",
  review: "agentRepository.mine.menu.review",
  reviewUpdate: "agentRepository.mine.menu.reviewUpdate",
};

export function MyAgentCard({
  agent,
  onEdit,
  onView,
  onApplyListing,
  onViewReview,
  onDelete,
  onEvaluate,
  onUsageGuide,
  highlighted = false,
  guideMenuOpen,
  onGuideMenuOpenChange,
  isApplying = false,
  isDeleting = false,
}: MyAgentCardProps) {
  const { t } = useTranslation("common");

  const title = agent.name?.trim() || t("agentRepository.card.untitled");
  const description =
    agent.description?.trim() || t("agentRepository.card.noDescription");
  const tags = agent.tags?.filter((tag) => tag.trim()) ?? [];
  const unavailableReasonLabels = getUnavailableReasonLabels(
    agent.unavailable_reasons ?? [],
    t
  );
  const { canOpen: published } = getAgentUsageGuideAccess({
    currentVersionNo: agent.current_version_no,
    permission: agent.permission,
  });
  const footerDate = formatMineDate(agent.version_create_time);
  const versionLabel = agent.version_label;
  const canEdit = agent.permission !== "READ_ONLY";
  const canView = (agent.current_version_no ?? 0) > 0;
  const canEvaluate = canView;
  const menuActions = getMineCardMenuActions(agent);
  const repositoryBadge = getMineCardRepositoryStatusBadge(
    agent.repository_info
  );

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
        onViewReview(
          agent,
          action === "reviewUpdate" ? "reviewUpdate" : "review"
        );
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

  if (published) {
    menuItems.push({
      key: "usageGuide",
      icon: <Share2 className="size-3.5" aria-hidden />,
      label: t("agentRepository.mine.menu.usageGuide"),
      className: guideMenuOpen ? "font-semibold" : undefined,
      onClick: onUsageGuide,
    });
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
    <ResourceCard
      title={title}
      className={`h-full ${
        highlighted ? "rounded-xl ring-2 ring-primary ring-offset-2" : ""
      }`}
      aria-current={highlighted ? "true" : undefined}
      onClick={onView}
      subtitle={
        versionLabel != null ? (
          <span className="flex min-w-0 items-center gap-1.5">
            <span
              className="size-1.5 shrink-0 rounded-full bg-primary"
              aria-hidden
            />
            <span className="min-w-0 truncate">
              {t("agentRepository.mine.currentVersion", {
                version: versionLabel,
              })}
            </span>
          </span>
        ) : undefined
      }
      icon={<MyAgentIcon agent={agent} size={44} iconSize={20} />}
      description={description}
      descriptionLines={2}
      tags={
        tags.length > 0 ? (
          <>
            {tags.map((tag) => (
              <span
                key={tag}
                className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                {getAgentRepositoryTagLabel(tag, t)}
              </span>
            ))}
          </>
        ) : undefined
      }
      statusRow={
        <div className="flex w-full min-w-0 items-center gap-2">
          <span
            className={`shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
              published
                ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                : "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
            }`}
          >
            {published
              ? t("agentRepository.mine.lifecycle.published")
              : t("agentRepository.mine.lifecycle.draft")}
          </span>
          <div className="flex min-w-0 flex-1 justify-end">
            {repositoryBadge ? (
              <span
                aria-label={`${t(repositoryBadge.labelKey)}${repositoryBadge.versionLabel ? ` · ${repositoryBadge.versionLabel}` : ""}`}
                className={`block w-fit max-w-full truncate rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
                  repositoryBadge.variant === "pending"
                    ? "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                    : repositoryBadge.variant === "rejected"
                      ? "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300"
                      : "bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300"
                }`}
              >
                {t(repositoryBadge.labelKey)}
                {repositoryBadge.versionLabel
                  ? ` · ${repositoryBadge.versionLabel}`
                  : null}
              </span>
            ) : null}
          </div>
        </div>
      }
      headerActions={
        menuItems.length > 0 || agent.is_available === false ? (
          <div className="grid h-[60px] grid-rows-2">
            <div className="flex items-center justify-end">
              {menuItems.length > 0 ? (
                <Dropdown
                  menu={{ items: menuItems }}
                  open={guideMenuOpen}
                  onOpenChange={onGuideMenuOpenChange}
                  trigger={["click"]}
                >
                  <Button
                    type="text"
                    size="small"
                    className="size-8 shrink-0 text-slate-400 hover:text-slate-600"
                    icon={<MoreHorizontal className="size-4" aria-hidden />}
                    aria-label={t("agentRepository.mine.menu.more")}
                    aria-haspopup="menu"
                  />
                </Dropdown>
              ) : null}
            </div>
            {agent.is_available === false ? (
              <div className="flex items-center justify-end">
                <Tooltip
                  title={
                    unavailableReasonLabels.length > 0
                      ? unavailableReasonLabels.join(", ")
                      : t("agentSelector.agentUnavailable")
                  }
                >
                  <span
                    className="rounded-md bg-red-50 px-1.5 py-0.5 text-[11px] font-medium text-red-700 dark:bg-red-500/10 dark:text-red-300"
                    aria-label={
                      unavailableReasonLabels.join(", ") ||
                      t("agentSelector.agentUnavailable")
                    }
                  >
                    {t("mcpConfig.status.unavailable")}
                  </span>
                </Tooltip>
              </div>
            ) : null}
          </div>
        ) : undefined
      }
      fixedHeaderLayout
      footerLayout="inline"
      meta={
        footerDate ? (
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3.5" aria-hidden />
            {footerDate}
          </span>
        ) : undefined
      }
      footer={
        canEdit ? (
          <Button
            type="text"
            size="small"
            className="!text-slate-600 hover:!bg-transparent hover:!text-blue-500"
            icon={<Pencil className="size-3.5" aria-hidden />}
            onClick={onEdit}
          >
            {t("agentRepository.mine.edit")}
          </Button>
        ) : (
          <Button
            type="text"
            size="small"
            className={
              canView
                ? "!text-slate-600 hover:!bg-transparent hover:!text-blue-500"
                : undefined
            }
            icon={<Eye className="size-3.5" aria-hidden />}
            onClick={onView}
            disabled={!canView}
          >
            {t("agentRepository.mine.view")}
          </Button>
        )
      }
    />
  );
}
