"use client";

import { useState } from "react";
import { App, Button, Empty, Spin } from "antd";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AgentRepositoryListingItem } from "@/types/agentRepository";
import { ReviewAgentList } from "./components/ReviewAgentList";
import {
  AgentRepositoryReviewConfirmModal,
  type AgentRepositoryReviewAction,
} from "./components/AgentRepositoryReviewConfirmModal";

interface ReviewCenterProps {
  listings: AgentRepositoryListingItem[];
  currentUserEmail?: string | null;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onRetry: () => void;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  updatingRepositoryId: number | null;
  onDetailClick: (listing: AgentRepositoryListingItem) => void;
  onApprove: (
    listing: AgentRepositoryListingItem,
    content?: string
  ) => Promise<unknown>;
  onReject: (
    listing: AgentRepositoryListingItem,
    content?: string
  ) => Promise<unknown>;
}

export function ReviewCenter({
  listings,
  currentUserEmail,
  isLoading,
  isError,
  isFetching,
  onRetry,
  page,
  pageSize,
  total,
  onPageChange,
  updatingRepositoryId,
  onDetailClick,
  onApprove,
  onReject,
}: ReviewCenterProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [reviewAction, setReviewAction] =
    useState<AgentRepositoryReviewAction | null>(null);
  const [reviewListing, setReviewListing] =
    useState<AgentRepositoryListingItem | null>(null);
  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 0;
  const showPagination = !isLoading && !isError && totalPages > 1;

  const closeReviewModal = () => {
    setReviewAction(null);
    setReviewListing(null);
  };
  const handleReviewConfirm = async (content?: string) => {
    if (!reviewListing || !reviewAction) return;
    const title =
      reviewListing.display_name?.trim() ||
      reviewListing.name?.trim() ||
      t("agentRepository.card.untitled");
    const isApprove = reviewAction === "approve";
    try {
      await (isApprove
        ? onApprove(reviewListing, content)
        : onReject(reviewListing, content));
      message.success(
        isApprove
          ? t("repository.review.approveSuccess", { name: title })
          : t("repository.review.rejectSuccess", { name: title })
      );
      closeReviewModal();
    } catch {
      message.error(
        isApprove
          ? t("repository.review.approveError")
          : t("repository.review.rejectError")
      );
      throw new Error("Review action failed");
    }
  };
  const isReviewModalLoading =
    reviewListing != null &&
    updatingRepositoryId === reviewListing.agent_repository_id;

  return (
    <div className="space-y-5">
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-200 py-16 text-center dark:border-slate-700">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("repository.review.loadError")}
          </p>
          <Button type="primary" onClick={onRetry} loading={isFetching}>
            {t("repository.common.retry")}
          </Button>
        </div>
      ) : listings.length === 0 ? (
        <Empty className="py-16" description={t("repository.review.empty")} />
      ) : (
        <>
          <ReviewAgentList
            listings={listings}
            currentUserEmail={currentUserEmail}
            updatingRepositoryId={updatingRepositoryId}
            onDetailClick={onDetailClick}
            onApprove={(listing) => {
              setReviewListing(listing);
              setReviewAction("approve");
            }}
            onReject={(listing) => {
              setReviewListing(listing);
              setReviewAction("reject");
            }}
          />
          <AgentRepositoryReviewConfirmModal
            open={reviewAction != null && reviewListing != null}
            action={reviewAction}
            listing={reviewListing}
            loading={isReviewModalLoading}
            onClose={closeReviewModal}
            onConfirm={handleReviewConfirm}
          />
          {showPagination ? (
            <div className="flex items-center justify-center gap-1.5 pt-2">
              <Button
                type="default"
                className="flex size-9 items-center justify-center rounded-lg p-0"
                disabled={page <= 1}
                onClick={() => onPageChange(Math.max(1, page - 1))}
                aria-label={t("repository.pagination.prev")}
              >
                <ChevronLeft className="size-4" aria-hidden />
              </Button>
              {Array.from({ length: totalPages }, (_, index) => index + 1).map(
                (pageNumber) => (
                  <Button
                    key={pageNumber}
                    type={pageNumber === page ? "primary" : "default"}
                    className="flex size-9 items-center justify-center rounded-lg p-0"
                    onClick={() => onPageChange(pageNumber)}
                    aria-label={t("repository.pagination.page", {
                      page: pageNumber,
                    })}
                    aria-current={pageNumber === page ? "page" : undefined}
                  >
                    {pageNumber}
                  </Button>
                )
              )}
              <Button
                type="default"
                className="flex size-9 items-center justify-center rounded-lg p-0"
                disabled={page >= totalPages}
                onClick={() => onPageChange(Math.min(totalPages, page + 1))}
                aria-label={t("repository.pagination.next")}
              >
                <ChevronRight className="size-4" aria-hidden />
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
