"use client";

import type { MenuProps } from "antd";
import { Button, Dropdown } from "antd";
import {
  Bot,
  Copy,
  Download,
  Eye,
  MoreHorizontal,
  PackageX,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import type { AgentRepositoryListingItem } from "@/types/agentRepository";
import ResourceCard from "@/components/resource/ResourceCard";

interface AgentRepositoryCardProps {
  listing: AgentRepositoryListingItem;
  showAdminMenu?: boolean;
  isTakingDown?: boolean;
  onCopyClick?: (listing: AgentRepositoryListingItem) => void;
  onDetailClick?: (listing: AgentRepositoryListingItem) => void;
  onTakeDown?: (listing: AgentRepositoryListingItem) => void;
}

export function AgentRepositoryCard({
  listing,
  showAdminMenu = false,
  isTakingDown = false,
  onCopyClick,
  onDetailClick,
  onTakeDown,
}: AgentRepositoryCardProps) {
  const { t } = useTranslation("common");

  const title =
    listing.display_name?.trim() ||
    listing.name?.trim() ||
    t("agentRepository.card.untitled");
  const author = listing.author?.trim();
  const tags = listing.tags?.filter((tag) => tag.trim()) ?? [];
  const toolCount = listing.tool_count ?? 0;
  const versionText = listing.version_label;
  const downloads = listing.downloads ?? 0;
  const showTagsRow = tags.length > 0 || toolCount > 0;
  const showMenu = showAdminMenu && onTakeDown != null;

  const menuItems: MenuProps["items"] = showMenu
    ? [
        {
          key: "takeDown",
          label: t("repository.listingStatus.takeDown"),
          icon: <PackageX className="size-3.5" aria-hidden />,
          danger: true,
          disabled: isTakingDown,
          onClick: () => onTakeDown(listing),
        },
      ]
    : [];

  return (
    <ResourceCard
      className="h-full"
      title={title}
      footerLayout="stacked"
      subtitle={author}
      icon={
        <div className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-xl text-primary">
          {listing.icon?.trim() ? (
            <span aria-hidden>{listing.icon.trim()}</span>
          ) : (
            <Bot className="size-5" aria-hidden />
          )}
        </div>
      }
      description={
        listing.description?.trim() || t("agentRepository.card.noDescription")
      }
      tags={
        showTagsRow ? (
          <>
            {tags.map((tag) => (
              <span
                key={tag}
                className="rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                {getAgentRepositoryTagLabel(tag, t)}
              </span>
            ))}
            {toolCount > 0 ? (
              <span className="rounded-md border border-slate-200 px-2 py-0.5 text-slate-500 dark:border-slate-700 dark:text-slate-400">
                {t("agentRepository.card.toolCount", { count: toolCount })}
              </span>
            ) : null}
          </>
        ) : undefined
      }
      meta={
        <>
          {versionText ? (
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <span className="size-1.5 rounded-full bg-primary" aria-hidden />
              {versionText}
            </span>
          ) : null}
          <span
            className="inline-flex items-center gap-1"
            aria-label={t("agentRepository.detail.downloads", {
              count: downloads.toLocaleString(),
            })}
          >
            <Download className="size-3.5" aria-hidden />
            {downloads.toLocaleString()}
          </span>
        </>
      }
      headerActions={
        showMenu ? (
          <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
            <Button
              type="text"
              size="small"
              className="size-8 shrink-0 text-slate-400 hover:text-slate-600"
              icon={<MoreHorizontal className="size-4" aria-hidden />}
              loading={isTakingDown}
              aria-label={t("agentRepository.mine.menu.more")}
            />
          </Dropdown>
        ) : undefined
      }
      footer={
        <div className="flex items-center gap-2">
          <Button
            type="primary"
            className="min-w-0 flex-1"
            icon={<Copy className="size-3.5" />}
            onClick={() => onCopyClick?.(listing)}
          >
            {t("agentRepository.card.copy")}
          </Button>
          <Button
            type="default"
            className="min-w-0 flex-1"
            icon={<Eye className="size-3.5" />}
            onClick={() => onDetailClick?.(listing)}
          >
            {t("agentRepository.card.detail")}
          </Button>
        </div>
      }
    />
  );
}
