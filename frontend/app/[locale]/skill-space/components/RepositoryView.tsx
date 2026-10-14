"use client";

import { Button, Input } from "antd";
import { Copy, Search } from "lucide-react";
import type { RefObject } from "react";
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
  columns,
  rows,
  gridHeight,
  gridRegionRef,
  onRetry,
  onInstall,
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
  columns: number;
  rows: number;
  gridHeight?: number;
  gridRegionRef: RefObject<HTMLDivElement | null>;
  onRetry: () => void;
  onInstall: (listing: SkillRepositoryListingItem) => void;
  onDetailClick: (listing: SkillRepositoryListingItem) => void;
  showAdminMenu: boolean;
  onTakeDown: (listing: SkillRepositoryListingItem) => void;
  installingRepositoryId: number | null;
  takingDownRepositoryId: number | null;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <div className="relative min-w-0 flex-1">
          <Input
            allowClear
            value={searchQuery}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={t("skillRepository.searchPlaceholder")}
            prefix={<Search className="size-4 text-slate-400" aria-hidden />}
            className="rounded-xl"
          />
        </div>
        <TagFilterPopover
          definitions={tagDefinitions}
          value={tagPredicates}
          onChange={onTagPredicatesChange}
        />
      </div>

      <div ref={gridRegionRef} className="min-h-0">
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
              items={listings}
              page={page}
              total={total}
              onPageChange={onPageChange}
              columns={columns}
              rows={rows}
              gridHeight={gridHeight}
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
                    <Button
                      type="text"
                      size="small"
                      className="!text-slate-600 hover:!bg-transparent hover:!text-blue-500"
                      icon={<Copy className="size-3.5" />}
                      loading={
                        installingRepositoryId === listing.skill_repository_id
                      }
                      onClick={() => onInstall(listing)}
                    >
                      {t("skillRepository.repository.copy")}
                    </Button>
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
