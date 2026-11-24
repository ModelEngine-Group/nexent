// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import RepositoryCardActions from "@/app/resource-space/components/RepositoryCardActions";
import RepositorySearchBar from "@/app/resource-space/components/RepositorySearchBar";
import RepositoryDisplayControls from "@/app/resource-space/components/RepositoryDisplayControls";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { Button } from "antd";
import { Copy } from "lucide-react";
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
  enhanced = false,
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
  enhanced?: boolean;
  onDetailClick: (listing: SkillRepositoryListingItem) => void;
  showAdminMenu: boolean;
  onTakeDown: (listing: SkillRepositoryListingItem) => void;
  installingRepositoryId: number | null;
  takingDownRepositoryId: number | null;
}) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const renderInstallAction = (listing: SkillRepositoryListingItem) => {
    const installed = listing.installation_state === "installed";
    const unknown =
      !listing.installation_state || listing.installation_state === "unknown";
    const busy = installingRepositoryId === listing.skill_repository_id;
    if (enhanced) {
      return (
        <RepositoryCardActions
          primary={
            installed
              ? undefined
              : {
                  label: t("resourceCenter.install"),
                  hint: unknown ? t("resourceCenter.sourceUnknown") : undefined,
                  disabled: unknown,
                  loading: busy,
                  onClick: () => {
                    if (!busy && !unknown) onInstall(listing);
                  },
                }
          }
        />
      );
    }
    return (
      <Button
        type="text"
        size="small"
        icon={<Copy className="size-3.5" />}
        loading={busy}
        onClick={(event) => {
          event.stopPropagation();
          if (!busy) onInstall(listing);
        }}
      >
        {t("skillRepository.repository.copy")}
      </Button>
    );
  };
  return (
    <div className={presentation ? "space-y-4" : "space-y-5"}>
      <RepositorySearchBar
        repository={Boolean(presentation)}
        value={searchQuery}
        onChange={onSearchChange}
        placeholder={t("skillRepository.searchPlaceholder")}
        filter={
          <TagFilterPopover
            appearance={presentation ? "select" : "button"}
            definitions={tagDefinitions}
            value={tagPredicates}
            onChange={onTagPredicatesChange}
            buttonClassName={
              presentation
                ? "!h-8 !w-full !justify-start !rounded !px-3 !text-sm"
                : undefined
            }
          />
        }
      >
        {!presentation || presentation.layout === "list" ? (
          <RepositoryDisplayControls />
        ) : null}
      </RepositorySearchBar>

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
    </div>
  );
}
