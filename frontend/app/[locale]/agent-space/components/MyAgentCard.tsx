"use client";

import { Button, Dropdown, Spin, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { useState } from "react";
import { useAgentRepositoryListings } from "@/hooks/agentRepository/useAgentRepositoryListings";
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
import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import { getUnavailableReasonLabels } from "@/lib/agentLabelMapper";
import {
  formatMineDate,
  getMineCardMenuActions,
  toMineRepositoryInfo,
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
  isApplying = false,
  isDeleting = false,
}: MyAgentCardProps) {
  const { t } = useTranslation("common");
  const [menuOpen, setMenuOpen] = useState(false);
  const {
    data: listingData,
    isLoading: isListingLoading,
    isError: isListingError,
    refetch,
  } = useAgentRepositoryListings(
    { agent_id: agent.agent_id, page: 1, page_size: 100 },
    menuOpen
  );

  const title = agent.name?.trim() || t("agentRepository.card.untitled");
  const description =
    agent.description?.trim() || t("agentRepository.card.noDescription");
  const tags = agent.tags?.filter((tag) => tag.trim()) ?? [];
  const unavailableReasonLabels = getUnavailableReasonLabels(
    agent.unavailable_reasons ?? [],
    t
  );
  const published = (agent.current_version_no ?? 0) > 0;
  const repositoryInfo = toMineRepositoryInfo(listingData?.items ?? []);
  const agentWithRepository = { ...agent, repository_info: repositoryInfo };
  const footerDate = formatMineDate(agent.version_create_time);
  const versionLabel = agent.version_label;
  const canEdit = agent.permission !== "READ_ONLY";
  const canView = (agent.current_version_no ?? 0) > 0;
  const canEvaluate = canView;
  const menuActions = listingData
    ? getMineCardMenuActions(agentWithRepository)
    : [];

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
          agentWithRepository,
          action === "reviewUpdate" ? "reviewUpdate" : "review"
        );
      },
    };
  });

  if (isListingLoading) {
    menuItems.unshift({
      key: "loading",
      label: <Spin size="small" />,
      disabled: true,
    });
  } else if (isListingError) {
    menuItems.unshift({
      key: "retry",
      label: t("repository.common.retry"),
      onClick: () => {
        void refetch();
      },
    });
  }

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
    <ResourceCard
      title={title}
      className="h-full"
      onClick={onView}
      subtitle={
        versionLabel != null ? (
          <span className="inline-flex items-center gap-1.5 truncate">
            <span
              className="size-1.5 shrink-0 rounded-full bg-primary"
              aria-hidden
            />
            {t("agentRepository.mine.currentVersion", {
              version: versionLabel,
            })}
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
      headerActions={
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {menuItems.length > 0 ? (
            <Dropdown
              menu={{ items: menuItems }}
              trigger={["click"]}
              onOpenChange={setMenuOpen}
            >
              <Button
                type="text"
                size="small"
                className="size-8 shrink-0 text-slate-400 hover:text-slate-600"
                icon={<MoreHorizontal className="size-4" aria-hidden />}
                aria-label={t("agentRepository.mine.menu.more")}
              />
            </Dropdown>
          ) : null}
          <div className="flex items-center gap-1.5">
            {agent.is_available === false ? (
              <Tooltip
                title={
                  unavailableReasonLabels.length > 0
                    ? unavailableReasonLabels.join(", ")
                    : t("agentSelector.agentUnavailable")
                }
              >
                <span
                  className="rounded-md bg-red-50 px-1.5 py-0.5 text-[11px] font-medium text-red-700 dark:bg-red-500/10 dark:text-red-300"
                  aria-label={unavailableReasonLabels.join(", ") || t("agentSelector.agentUnavailable")}
                >
                  {t("mcpConfig.status.unavailable")}
                </span>
              </Tooltip>
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
      }
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
