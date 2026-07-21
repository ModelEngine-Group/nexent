"use client";

import { Button, Input } from "antd";
import { Copy, Eye, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SkillRepositoryCard } from "./SkillRepositoryCard";
import { AsyncContent, PaginationBar } from "./SkillRepositoryControls";
import type { SkillRepositoryListingItem } from "@/types/skillRepository";

export function RepositoryView({
  searchQuery,
  onSearchChange,
  listings,
  isLoading,
  isError,
  isFetching,
  page,
  pageSize,
  total,
  onPageChange,
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
  listings: SkillRepositoryListingItem[];
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
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
      <div className="relative">
        <Input
          allowClear
          value={searchQuery}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={t("skillRepository.searchPlaceholder")}
          prefix={<Search className="size-4 text-slate-400" aria-hidden />}
          className="h-11 rounded-xl"
        />
      </div>

      <p className="text-sm text-slate-500 dark:text-slate-400">
        {t("skillRepository.repository.summary", { count: total })}
      </p>

      <AsyncContent
        isLoading={isLoading}
        isError={isError}
        isFetching={isFetching}
        onRetry={onRetry}
        isEmpty={listings.length === 0}
        emptyDescription={t("skillRepository.repository.empty")}
      >
        <>
          <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {listings.map((listing) => (
              <SkillRepositoryCard
                key={listing.skill_repository_id}
                listing={listing}
                onDetailClick={() => onDetailClick(listing)}
                showAdminMenu={showAdminMenu || listing.can_take_down === true}
                isTakingDown={
                  takingDownRepositoryId === listing.skill_repository_id
                }
                onTakeDown={() => onTakeDown(listing)}
                action={
                  <div className="flex items-center gap-2">
                    <Button
                      type="primary"
                      className="flex-1 text-sm"
                      icon={<Copy className="size-3.5" />}
                      loading={
                        installingRepositoryId === listing.skill_repository_id
                      }
                      onClick={() => onInstall(listing)}
                    >
                      {t("skillRepository.repository.copy")}
                    </Button>
                    <Button
                      type="default"
                      className="flex-1 text-sm"
                      icon={<Eye className="size-3.5" />}
                      onClick={() => onDetailClick(listing)}
                    >
                      {t("skillRepository.common.detail")}
                    </Button>
                  </div>
                }
              />
            ))}
          </div>
          <PaginationBar
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={onPageChange}
          />
        </>
      </AsyncContent>
    </div>
  );
}
