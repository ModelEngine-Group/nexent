// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import RepositoryCardActions from "@/app/resource-space/components/RepositoryCardActions";
import ResourcePublishedAt from "@/app/resource-space/components/ResourcePublishedAt";
import type { ReactNode } from "react";
import type { MenuProps } from "antd";
import { Button, Dropdown, Tag } from "antd";
import { Bot, Download, MoreHorizontal, Trash2 } from "lucide-react";
import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";
import { useTranslation } from "react-i18next";

import ResourceCard from "@/components/resource/ResourceCard";
import SkillTypeIcon from "@/components/skill/SkillTypeIcon";
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
  const presentation = useRepositoryPresentation();
  const displayName = useUserDisplayName();
  const tags = listing.tags?.filter((tag) => tag.trim()) ?? [];
  const author = listing.author?.trim()
    ? displayName(listing.author_cas_username, listing.author.trim())
    : displayName(
        listing.submitted_by_cas_username,
        listing.submitted_by?.trim() || ""
      );
  const menuItems: MenuProps["items"] =
    (listing.can_take_down ?? showAdminMenu) &&
    listing.status === "shared" &&
    onTakeDown != null
      ? [
          {
            key: "takeDown",
            label: t("skillRepository.action.status.notShared"),
            icon: <Trash2 className="size-3.5" aria-hidden />,
            danger: true,
            disabled: isTakingDown,
            onClick: onTakeDown,
          },
        ]
      : [];

  const tagChips = tags.map((tag) => (
    <span
      key={tag}
      className={
        presentation
          ? "h-5 rounded bg-[rgba(25,25,25,0.05)] px-2 text-xs leading-5 font-normal text-[#393939]"
          : "rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
      }
    >
      {tag}
    </span>
  ));

  return (
    <ResourceCard
      actionsOnly={presentation?.layout === "list"}
      className="h-full"
      title={listing.name}
      subtitle={
        presentation && author ? (
          <span title={author}>{author}</span>
        ) : undefined
      }
      footerLayout="inline"
      icon={
        presentation ? (
          <SkillTypeIcon
            className="rounded"
            name={listing.name}
            tags={listing.tags}
            icon={listing.icon}
          />
        ) : (
          <div className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Bot className="size-5" aria-hidden />
          </div>
        )
      }
      description={
        listing.description || t("skillRepository.common.noDescription")
      }
      tags={
        presentation ? (
          tags.length > 0 ? (
            <>{tagChips}</>
          ) : (
            // Always reserve the tag row so repository cards keep equal
            // heights regardless of whether the listing has tags.
            <div className="h-5" aria-hidden />
          )
        ) : tags.length > 0 ? (
          <>{tagChips}</>
        ) : null
      }
      headerActions={
        presentation ? undefined : (
          <span
            className="inline-flex items-center gap-1"
            aria-label={t("skillRepository.card.downloadAria", {
              count: listing.downloads ?? 0,
            })}
          >
            <Download className="size-3.5" aria-hidden />
            {(listing.downloads ?? 0).toLocaleString()}
          </span>
        )
      }
      actions={
        !presentation && menuItems.length > 0 ? (
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
        <>
          {" "}
          {!presentation && author ? (
            <span className="block truncate" title={author}>
              {presentation
                ? `${t("skillRepository.detail.author")}: ${author}`
                : author}
            </span>
          ) : undefined}{" "}
          {presentation && (
            <span>
              {t("resourceCenter.skillInstalls", {
                count: listing.downloads ?? 0,
              })}
            </span>
          )}
          {!presentation && (
            <ResourcePublishedAt value={listing.published_at} />
          )}
        </>
      }
      footer={
        presentation ? (
          <div className="inline-flex items-center gap-1">
            {action}
            <RepositoryCardActions
              takeDown={
                menuItems.length > 0
                  ? {
                      label: t("skillRepository.action.status.notShared"),
                      loading: isTakingDown,
                      onClick: () => onTakeDown?.(),
                    }
                  : undefined
              }
            />
          </div>
        ) : (
          action
        )
      }
      onClick={onDetailClick}
    />
  );
}
