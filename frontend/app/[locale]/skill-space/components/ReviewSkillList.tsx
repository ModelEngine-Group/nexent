"use client";

import { Button, Tag } from "antd";
import { Bot, Check, Eye, X } from "lucide-react";

import { AsyncContent, PaginationBar } from "./SkillRepositoryControls";
import type {
  SkillRepositoryListingItem,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";

const GRID_COLS = "grid-cols-[minmax(0,2fr)_180px_120px_260px]";

const REVIEW_STATUS_LABELS: Record<SkillRepositoryListingStatus, string> = {
  not_shared: "未上架",
  pending_review: "待审核",
  rejected: "已驳回",
  shared: "已通过",
};

const REVIEW_STATUS_COLORS: Record<SkillRepositoryListingStatus, string> = {
  not_shared: "default",
  pending_review: "processing",
  rejected: "error",
  shared: "success",
};

function getSubmitterDisplay(submittedBy: string | null | undefined) {
  return submittedBy?.trim() || "未知提交人";
}

export function ReviewSkillList({
  listings,
  isLoading,
  isError,
  isFetching,
  page,
  pageSize,
  total,
  onPageChange,
  onRetry,
  updatingRepositoryId,
  onDetailClick,
  onApprove,
  onReject,
}: {
  listings: SkillRepositoryListingItem[];
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onRetry: () => void;
  updatingRepositoryId: number | null;
  onDetailClick: (listing: SkillRepositoryListingItem) => void;
  onApprove: (listing: SkillRepositoryListingItem) => void;
  onReject: (listing: SkillRepositoryListingItem) => void;
}) {
  return (
    <div className="flex flex-col gap-5">
      <AsyncContent
        isLoading={isLoading}
        isError={isError}
        isFetching={isFetching}
        onRetry={onRetry}
        isEmpty={listings.length === 0}
        emptyDescription="暂无审核记录"
      >
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900">
          <div className="inline-block min-w-full">
            <div
              className={`hidden min-w-[640px] ${GRID_COLS} gap-4 border-b border-slate-200 bg-slate-50 px-5 py-4 text-xs font-medium text-slate-500 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-400 lg:grid lg:items-center`}
            >
              <span>Skill</span>
              <span>提交人</span>
              <span>状态</span>
              <span>操作</span>
            </div>

            <ul className="divide-y divide-slate-200 dark:divide-slate-700">
              {listings.map((listing) => {
                const isUpdating =
                  updatingRepositoryId === listing.skill_repository_id;
                const isPendingReview = listing.status === "pending_review";

                return (
                  <li
                    key={listing.skill_repository_id}
                    className={`min-w-[640px] ${GRID_COLS} gap-4 px-5 py-4 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40 lg:grid lg:items-center`}
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <Bot className="size-5" aria-hidden />
                      </div>
                      <div className="min-w-0">
                        <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                          {listing.name || "未命名 Skill"}
                        </h3>
                        {listing.description ? (
                          <p className="mt-1 line-clamp-1 text-xs text-slate-500 dark:text-slate-400">
                            {listing.description}
                          </p>
                        ) : null}
                      </div>
                    </div>

                    <div className="truncate text-sm text-slate-500 dark:text-slate-400">
                      {getSubmitterDisplay(listing.submitted_by)}
                    </div>

                    <div>
                      <Tag color={REVIEW_STATUS_COLORS[listing.status]}>
                        {REVIEW_STATUS_LABELS[listing.status]}
                      </Tag>
                    </div>

                    <div className="flex flex-wrap items-center justify-start gap-2">
                      <Button
                        type="default"
                        size="small"
                        icon={<Eye className="size-4" aria-hidden />}
                        onClick={() => onDetailClick(listing)}
                        disabled={isUpdating}
                      >
                        详情
                      </Button>
                      {isPendingReview ? (
                        <>
                          <Button
                            type="primary"
                            size="small"
                            icon={<Check className="size-4" aria-hidden />}
                            onClick={() => onApprove(listing)}
                            loading={isUpdating}
                            disabled={isUpdating}
                          >
                            通过
                          </Button>
                          <Button
                            danger
                            size="small"
                            icon={<X className="size-4" aria-hidden />}
                            onClick={() => onReject(listing)}
                            loading={isUpdating}
                            disabled={isUpdating}
                          >
                            驳回
                          </Button>
                        </>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
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
