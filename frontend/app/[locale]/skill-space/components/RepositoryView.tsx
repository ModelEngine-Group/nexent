"use client";

import { Button, Input } from "antd";
import { Copy, Eye, Search } from "lucide-react";

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

  return (
    <div className="space-y-5">
      <div className="relative">
        <Input
          allowClear
          value={searchQuery}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="搜索 Skill 名称或描述"
          prefix={<Search className="size-4 text-slate-400" aria-hidden />}
          className="h-11 rounded-xl"
        />
      </div>

      <AsyncContent
        isLoading={isLoading}
        isError={isError}
        isFetching={isFetching}
        onRetry={onRetry}
        isEmpty={listings.length === 0}
        emptyDescription="暂无已上架 Skill"
      >
        <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {listings.map((listing) => (
            <SkillRepositoryCard
              key={listing.skill_repository_id}
              listing={listing}
              onDetailClick={() => onDetailClick(listing)}
              showAdminMenu={showAdminMenu}
              isTakingDown={takingDownRepositoryId === listing.skill_repository_id}
              onTakeDown={() => onTakeDown(listing)}
              action={
                <div className="flex items-center gap-2">
                  <Button
                    type="primary"
                    className="flex-1 text-sm"
                    icon={<Copy className="size-3.5" />}
                    loading={installingRepositoryId === listing.skill_repository_id}
                    onClick={() => onInstall(listing)}
                  >
                    复制
                  </Button>
                  <Button
                    type="default"
                    className="flex-1 text-sm"
                    icon={<Eye className="size-3.5" />}
                    onClick={() => onDetailClick(listing)}
                  >
                    详情
                  </Button>
                </div>
              }
            />
          ))}
        </div>
      </AsyncContent>

      <PaginationBar
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={onPageChange}
      />
    </div>
  );
}
