// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import RepositoryDisplayControls from "@/components/repository/RepositoryDisplayControls";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { Button, Input, Modal, Tooltip } from "antd";
import { useState } from "react";
import { Copy, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import TagFilterPopover from "@/components/tag/TagFilterPopover";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";

import { SkillRepositoryCard } from "./SkillRepositoryCard";
import { AsyncContent } from "./SkillRepositoryControls";
import type { SkillRepositoryListingItem } from "@/types/skillRepository";
import type {
  TagDefinition,
  TagResourcePredicate,
} from "@/types/tagManagement";

export function RepositoryView({
  searchQuery,
  onSearchChange,
  tagDefinitions,
  tagPredicates,
  onTagPredicatesChange,
  listings,
  isLoading,
  isError,
  isFetching,
  page,
  total,
  onPageChange,
  pageSize,
  onPageSizeChange,
  onRetry,
  onInstall,
  onUninstall,
  onDetailClick,
  showAdminMenu,
  onTakeDown,
  installingRepositoryId,
  takingDownRepositoryId,
}: {
  searchQuery: string;
  onSearchChange: (value: string) => void;
  tagDefinitions: TagDefinition[];
  tagPredicates: TagResourcePredicate[];
  onTagPredicatesChange: (value: TagResourcePredicate[]) => void;
  listings: SkillRepositoryListingItem[];
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  page: number;
  total: number;
  onPageChange: (page: number) => void;
  pageSize: number;
  onPageSizeChange: (size: number) => void;
  onRetry: () => void;
  onInstall: (listing: SkillRepositoryListingItem) => void;
  onUninstall?: (
    listing: SkillRepositoryListingItem,
    copy: { skill_id: number; name: string },
  ) => void;
  onDetailClick: (listing: SkillRepositoryListingItem) => void;
  showAdminMenu: boolean;
  onTakeDown: (listing: SkillRepositoryListingItem) => void;
  installingRepositoryId: number | null;
  takingDownRepositoryId: number | null;
}) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const [uninstallTargetId, setUninstallTargetId] = useState<number | null>(
    null,
  );
  const uninstallTarget = listings.find(
    (listing) => listing.skill_repository_id === uninstallTargetId,
  );
  const renderInstallAction = (listing: SkillRepositoryListingItem) => {
    const installed = listing.installation_state === "installed";
    const unknown =
      !listing.installation_state || listing.installation_state === "unknown";
    const copies = listing.installed_copies ?? [];
    const busy = installingRepositoryId === listing.skill_repository_id;
    return (
      <span className="inline-flex items-center gap-2">
        <Tooltip
          title={
            onUninstall && unknown
              ? t("resourceCenter.sourceUnknown")
              : onUninstall && installed && !copies.length
                ? t("resourceCenter.sourceAlreadyAvailable")
                : undefined
          }
        >
          <Button
            type={onUninstall ? "default" : "text"}
            size={onUninstall ? "middle" : "small"}
            className={
              onUninstall
                ? "h-8 min-w-[88px] max-w-[190px] rounded px-4 text-sm font-normal leading-[22px]"
                : undefined
            }
            icon={onUninstall ? undefined : <Copy className="size-3.5" />}
            loading={busy}
            disabled={
              Boolean(onUninstall) &&
              (unknown ||
                (installed && !copies.some((copy) => copy.can_uninstall)))
            }
            onClick={(event) => {
              event.stopPropagation();
              if (busy) return;
              if (!onUninstall || (!installed && !unknown)) {
                onInstall(listing);
              } else if (installed && onUninstall) {
                if (copies.length === 1 && copies[0].can_uninstall)
                  onUninstall(listing, copies[0]);
                else if (copies.some((copy) => copy.can_uninstall))
                  setUninstallTargetId(listing.skill_repository_id);
              }
            }}
          >
            {t(
              onUninstall
                ? installed
                  ? "resourceCenter.uninstall"
                  : "resourceCenter.install"
                : "skillRepository.repository.copy",
            )}
          </Button>
        </Tooltip>
      </span>
    );
  };
  return (
    <div className={presentation ? "space-y-4" : "space-y-5"}>
      <div
        className={
          presentation
            ? "flex flex-wrap items-center gap-2"
            : "flex items-center gap-3"
        }
      >
        <div
          className={
            presentation
              ? "relative w-[594px] min-w-0 max-w-full"
              : "relative min-w-0 flex-1"
          }
        >
          <Input
            allowClear
            value={searchQuery}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={t("skillRepository.searchPlaceholder")}
            prefix={<Search className="size-4 text-[#777777]" aria-hidden />}
            className={
              presentation
                ? "h-8 gap-1 rounded border-[#C9C9C9] bg-white px-3 py-[5px] text-sm leading-[22px] [&_input::placeholder]:text-[#AEAEAE]"
                : "rounded-xl"
            }
          />
        </div>
        <TagFilterPopover
          appearance={presentation ? "select" : "button"}
          definitions={tagDefinitions}
          value={tagPredicates}
          onChange={onTagPredicatesChange}
          buttonClassName={
            presentation
              ? "!h-8 !w-[296px] max-w-full !justify-start !rounded !border-[#C9C9C9] !px-3 !text-sm"
              : undefined
          }
        />
        {!presentation || presentation.layout === "list" ? (
          <RepositoryDisplayControls />
        ) : null}
      </div>

      <div className="min-h-0">
        <AsyncContent
          isLoading={isLoading}
          isError={isError}
          isFetching={isFetching}
          onRetry={onRetry}
          isEmpty={listings.length === 0}
          emptyDescription={t("skillRepository.repository.empty")}
        >
          <>
            <ResourceCardGrid
              onListSelect={onDetailClick}
              items={listings}
              page={page}
              total={total}
              onPageChange={onPageChange}
              pageSize={pageSize}
              onPageSizeChange={presentation ? onPageSizeChange : undefined}
              paginateItems={false}
              showToolbar={false}
              renderItem={(listing) => (
                <SkillRepositoryCard
                  key={listing.skill_repository_id}
                  listing={listing}
                  onDetailClick={() => onDetailClick(listing)}
                  showAdminMenu={showAdminMenu}
                  isTakingDown={
                    takingDownRepositoryId === listing.skill_repository_id
                  }
                  onTakeDown={() => onTakeDown(listing)}
                  action={renderInstallAction(listing)}
                />
              )}
            />
          </>
        </AsyncContent>
      </div>
      <Modal
        open={Boolean(
          uninstallTarget && uninstallTarget.installation_state === "installed",
        )}
        title={t("resourceCenter.uninstall")}
        closable={{ "aria-label": t("common.close") }}
        onCancel={() => setUninstallTargetId(null)}
        footer={null}
        centered
      >
        <div className="flex flex-col gap-2">
          {(uninstallTarget?.installed_copies ?? []).map((copy) => (
            <Button
              key={copy.skill_id}
              disabled={
                !copy.can_uninstall ||
                installingRepositoryId === uninstallTargetId
              }
              onClick={() => {
                if (!uninstallTarget || !copy.can_uninstall) return;
                setUninstallTargetId(null);
                onUninstall?.(uninstallTarget, copy);
              }}
            >
              {copy.name}
            </Button>
          ))}
        </div>
      </Modal>
    </div>
  );
}
