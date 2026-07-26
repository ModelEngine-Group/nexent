"use client";

import type { MenuProps } from "antd";
import { Button, Card, Dropdown } from "antd";
import { Bot, Copy, Download, Eye, MoreHorizontal, PackageX } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AgentRepositoryListingItem } from "@/types/agentRepository";

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
    listing.display_name?.trim() || listing.name?.trim() || t("agentRepository.card.untitled");
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
          label: t("agentRepository.mine.reviewModal.takeDown"),
          icon: <PackageX className="size-3.5" aria-hidden />,
          danger: true,
          disabled: isTakingDown,
          onClick: () => onTakeDown(listing),
        },
      ]
    : [];

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
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-xl text-primary">
            {listing.icon?.trim() ? (
              <span aria-hidden>{listing.icon.trim()}</span>
            ) : (
              <Bot className="size-5" aria-hidden />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-base font-semibold text-slate-900 dark:text-slate-100">
              {title}
            </h3>
            {author ? (
              <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                {author}
              </p>
            ) : null}
          </div>
        </div>
        {showMenu ? (
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
        ) : null}
      </div>

      <p className="mt-3 line-clamp-2 min-h-[2.75rem] text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        {listing.description?.trim() || t("agentRepository.card.noDescription")}
      </p>

      {showTagsRow ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {tags.map((tag) => (
            <span
              key={tag}
              className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
            >
              {tag}
            </span>
          ))}
          {toolCount > 0 ? (
            <span className="rounded-md border border-slate-200 px-2 py-0.5 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
              {t("agentRepository.card.toolCount", { count: toolCount })}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="mt-auto flex flex-col gap-3 pt-4">
        <div className="flex min-h-[1.75rem] items-center justify-between gap-4 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
          {versionText ? (
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <span className="size-1.5 rounded-full bg-primary" aria-hidden />
              {versionText}
            </span>
          ) : (
            <span />
          )}
          <div className="flex shrink-0 items-center gap-1">
            <span
              className="inline-flex items-center gap-1"
              aria-label={t("agentRepository.detail.downloads", {
                count: downloads.toLocaleString(),
              })}
            >
              <Download className="size-3.5" aria-hidden />
              {downloads.toLocaleString()}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="small"
            className="flex-1"
            icon={<Copy className="size-3.5" />}
            onClick={() => onCopyClick?.(listing)}
          >
            {t("agentRepository.card.copy")}
          </Button>
          <Button
            size="small"
            type="default"
            className="flex-1"
            icon={<Eye className="size-3.5" />}
            onClick={() => onDetailClick?.(listing)}
          >
            {t("agentRepository.card.detail")}
          </Button>
        </div>
      </div>
    </Card>
  );
}
