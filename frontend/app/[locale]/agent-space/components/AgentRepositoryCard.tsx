"use client";

import { Button, Card } from "antd";
import { Bot, Copy, Download, Eye } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AgentRepositoryListingItem } from "@/types/agentRepository";

interface AgentRepositoryCardProps {
  listing: AgentRepositoryListingItem;
  categoryName?: string | null;
  onDetailClick?: (listing: AgentRepositoryListingItem) => void;
}

export function AgentRepositoryCard({
  listing,
  categoryName,
  onDetailClick,
}: AgentRepositoryCardProps) {
  const { t } = useTranslation("common");

  const title =
    listing.display_name?.trim() || listing.name?.trim() || t("agentRepository.card.untitled");
  const author = listing.author?.trim();
  const category =
    categoryName?.trim() || t("agentRepository.review.unknownCategory");
  const subtitle = author ? `${author} · ${category}` : category;
  const tags = listing.tags?.filter((tag) => tag.trim()) ?? [];
  const toolCount = listing.tool_count ?? 0;
  const versionText = listing.version_label;
  const downloads = listing.downloads ?? 0;
  const showMetaRow = versionText != null || downloads > 0;
  const showTagsRow = tags.length > 0 || toolCount > 0;

  return (
    <Card className="flex h-full flex-col rounded-2xl border border-slate-200 p-5 shadow-sm">
      <div className="flex min-h-0 flex-1 flex-col gap-3.5">
        <div className="flex min-w-0 items-start gap-3">
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
            <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
              {subtitle}
            </p>
          </div>
        </div>

        <p className="line-clamp-2 flex-1 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
          {listing.description?.trim() || t("agentRepository.card.noDescription")}
        </p>

        {showTagsRow ? (
          <div className="flex flex-wrap items-center gap-1.5">
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

        {showMetaRow ? (
          <div className="flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            {versionText ? (
              <span className="flex items-center gap-1.5">
                <span className="size-1.5 rounded-full bg-primary" />
                {versionText}
              </span>
            ) : (
              <span />
            )}
            {downloads > 0 ? (
              <span className="flex items-center gap-1">
                <Download className="size-3.5" aria-hidden />
                {downloads.toLocaleString()}
              </span>
            ) : null}
          </div>
        ) : null}

        <div className="mt-auto flex items-center gap-2">
          <Button
            size="small"
            className="flex-1"
            disabled
            icon={<Copy className="size-3.5" />}
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
