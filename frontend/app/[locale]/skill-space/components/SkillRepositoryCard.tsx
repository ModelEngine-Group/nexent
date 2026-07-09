"use client";

import type { ReactNode } from "react";
import type { MenuProps } from "antd";
import { Button, Dropdown, Tag } from "antd";
import { Bot, Download, MoreHorizontal, PackageX } from "lucide-react";

import { STATUS_COLORS, STATUS_LABELS } from "./skillRepositoryShared";
import type {
  SkillRepositoryListingItem,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";

export function StatusTag({
  status,
}: {
  status: SkillRepositoryListingStatus;
}) {
  return <Tag color={STATUS_COLORS[status]}>{STATUS_LABELS[status]}</Tag>;
}

export function SkillRepositoryCard({
  listing,
  onDetailClick,
  action,
  showAdminMenu = false,
  isTakingDown = false,
  onTakeDown,
}: {
  listing: SkillRepositoryListingItem;
  onDetailClick?: () => void;
  action?: ReactNode;
  showAdminMenu?: boolean;
  isTakingDown?: boolean;
  onTakeDown?: () => void;
}) {
  const showMenu = showAdminMenu && onTakeDown != null;
  const tags = listing.tags?.filter((tag) => tag.trim()) ?? [];
  const menuItems: MenuProps["items"] = showMenu
    ? [
        {
          key: "takeDown",
          label: "下架",
          icon: <PackageX className="size-3.5" aria-hidden />,
          danger: true,
          disabled: isTakingDown,
          onClick: onTakeDown,
        },
      ]
    : [];

  return (
    <article
      className="flex min-h-[220px] flex-col rounded-xl border border-border bg-background p-4 shadow-sm transition hover:border-primary/40 hover:shadow-md"
      onDoubleClick={onDetailClick}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Bot className="size-5" aria-hidden />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-slate-900 dark:text-slate-100">
              {listing.name}
            </h3>
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
              aria-label="更多操作"
            />
          </Dropdown>
        ) : null}
      </div>

      <p className="mt-3 line-clamp-2 min-h-[2.75rem] text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        {listing.description || "暂无描述"}
      </p>

      {tags.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {tags.map((tag) => (
            <span
              key={tag}
              className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
            >
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-auto flex flex-col gap-3 pt-4">
        <div className="flex min-h-[1.75rem] items-center justify-end gap-4 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
          <span
            className="inline-flex items-center gap-1"
            aria-label={`下载 ${listing.downloads ?? 0}`}
          >
            <Download className="size-3.5" aria-hidden />
            {(listing.downloads ?? 0).toLocaleString()}
          </span>
        </div>
        {action}
      </div>
    </article>
  );
}
