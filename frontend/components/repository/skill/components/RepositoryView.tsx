// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import RepositoryDisplayControls from "@/components/repository/RepositoryDisplayControls";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { Button, Dropdown, Input, Tooltip } from "antd";
import { ChevronDown, Copy, Search } from "lucide-react";
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
    copy: { skill_id: number; name: string }
  ) => void;
  onDetailClick: (listing: SkillRepositoryListingItem) => void;
  showAdminMenu: boolean;
  onTakeDown: (listing: SkillRepositoryListingItem) => void;
  installingRepositoryId: number | null;
  takingDownRepositoryId: number | null;
}) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
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
                  action={
                    <Dropdown
                      disabled={!onUninstall}
                      menu={{
                        items: [
                          {
                            key: "install",
                            label: t("resourceCenter.installAnother"),
                            onClick: () => onInstall(listing),
                          },
                          ...(listing.installed_copies || []).map((copy) => ({
                            key: String(copy.skill_id),
                            label: `${t("resourceCenter.uninstall")}: ${copy.name}`,
                            disabled: !copy.can_uninstall,
                            onClick: () => onUninstall?.(listing, copy),
                          })),
                        ],
                      }}
                      trigger={["click"]}
                    >
                      <Tooltip
                        title={
                          listing.installation_state === "unknown"
                            ? t("resourceCenter.sourceUnknown")
                            : undefined
                        }
                      >
                        <span className="inline-flex items-center -space-x-px">
                          <Button
                            type={onUninstall ? "default" : "text"}
                            size={onUninstall ? "middle" : "small"}
                            className={
                              presentation && onUninstall
                                ? "h-8 min-w-[88px] max-w-[190px] gap-1 rounded-l rounded-r-none border-[#C9C9C9] bg-white px-4 py-[5px] text-sm leading-[22px] font-normal text-[#191919]"
                                : onUninstall
                                  ? "h-8 min-w-[88px] max-w-[190px] gap-1 rounded border-[#C9C9C9] bg-white px-4 py-[5px] text-sm leading-[22px] font-normal text-[#191919]"
                                  : "!text-slate-600 hover:!bg-transparent hover:!text-blue-500"
                            }
                            icon={
                              onUninstall ? undefined : (
                                <Copy className="size-3.5" />
                              )
                            }
                            loading={
                              installingRepositoryId ===
                              listing.skill_repository_id
                            }
                            onClick={(event) => {
                              if (
                                !onUninstall ||
                                (presentation &&
                                  listing.installation_state ===
                                    "not_installed")
                              ) {
                                event.stopPropagation();
                                onInstall(listing);
                              }
                            }}
                          >
                            {onUninstall
                              ? t(
                                  listing.installation_state === "installed"
                                    ? "resourceCenter.installed"
                                    : "resourceCenter.install"
                                )
                              : t("skillRepository.repository.copy")}
                          </Button>
                          {presentation && onUninstall ? (
                            <Button
                              className="!size-8 !min-w-8 !rounded-l-none !rounded-r !border-[#C9C9C9] !bg-white !p-0 !text-[#191919]"
                              icon={<ChevronDown size={10} aria-hidden />}
                              aria-label={t("resourceCenter.actions")}
                              disabled={
                                installingRepositoryId ===
                                listing.skill_repository_id
                              }
                            />
                          ) : null}
                        </span>
                      </Tooltip>
                    </Dropdown>
                  }
                />
              )}
            />
          </>
        </AsyncContent>
      </div>
    </div>
  );
}
