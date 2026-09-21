"use client";

import type { ReactNode } from "react";
import type { MenuProps } from "antd";
import { Button, Dropdown, Tag } from "antd";
import { Bot, Download, MoreHorizontal, PackageX } from "lucide-react";
import { useTranslation } from "react-i18next";

import ResourceCard from "@/components/resource/ResourceCard";
import type {
  SkillRepositoryListingItem,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";
import {
  getSkillRepositoryStatusLabel,
  STATUS_COLORS,
} from "./skillRepositoryShared";

export function StatusTag({
  status,
}: {
  status: SkillRepositoryListingStatus;
}) {
  const { t } = useTranslation("common");
  return (
    <Tag color={STATUS_COLORS[status]}>
      {getSkillRepositoryStatusLabel(t, status)}
    </Tag>
  );
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
  const { t } = useTranslation("common");
  const tags = listing.tags?.filter((tag) => tag.trim()) ?? [];
  const menuItems: MenuProps["items"] =
    showAdminMenu && onTakeDown != null
      ? [
          {
            key: "takeDown",
            label: t("skillRepository.action.status.notShared"),
            icon: <PackageX className="size-3.5" aria-hidden />,
            danger: true,
            disabled: isTakingDown,
            onClick: onTakeDown,
          },
        ]
      : [];

  return (
    <ResourceCard
      className="h-full"
      title={listing.name}
      footerLayout="inline"
      icon={
        <div className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Bot className="size-5" aria-hidden />
        </div>
      }
      description={
        listing.description || t("skillRepository.common.noDescription")
      }
      tags={
        <div className="flex min-h-7 flex-wrap gap-2">
          {tags.map((tag) => (
            <span
              key={tag}
              className="rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
            >
              {tag}
            </span>
          ))}
        </div>
      }
      headerActions={
        <span
          className="inline-flex items-center gap-1"
          aria-label={t("skillRepository.card.downloadAria", {
            count: listing.downloads ?? 0,
          })}
        >
          <Download className="size-3.5" aria-hidden />
          {(listing.downloads ?? 0).toLocaleString()}
        </span>
      }
      actions={
        menuItems.length > 0 ? (
          <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
            <Button
              type="text"
              size="small"
              className="size-8 shrink-0 text-slate-400 hover:text-slate-600"
              icon={<MoreHorizontal className="size-4" aria-hidden />}
              loading={isTakingDown}
              aria-label={t("skillRepository.common.moreActions")}
            />
          </Dropdown>
        ) : undefined
      }
      meta={
        listing.author?.trim() ? (
          <span className="truncate">{listing.author.trim()}</span>
        ) : undefined
      }
      footer={action}
      onClick={onDetailClick}
    />
  );
}
