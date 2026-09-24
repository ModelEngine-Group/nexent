"use client";

import { useMemo, useState } from "react";
import { App, Button, Empty, Spin } from "antd";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { AgentDetail } from "@/components/agents/agent-detail";
import { USER_ROLES } from "@/const/auth";
import {
  useAgentRepositoryListings,
  useUpdateAgentRepositoryStatus,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import { useRepositoryAgentDetail } from "@/hooks/agentRepository/useRepositoryAgentDetail";

import type { AgentRepositoryListingItem } from "@/types/agentRepository";
import { ReviewAgentList } from "./components/ReviewAgentList";
import { RepositoryAgentIcon } from "./components/RepositoryAgentIcon";
import {
  AgentRepositoryReviewConfirmModal,
  type AgentRepositoryReviewAction,
} from "./components/AgentRepositoryReviewConfirmModal";

const REVIEW_PAGE_SIZE = 10;

export function ReviewCenter({ active }: { active: boolean }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();
  const isAdmin = user?.role === USER_ROLES.ADMIN;
  const currentUserEmail = user?.email;
  const [page, setPage] = useState(1);
  const pageSize = REVIEW_PAGE_SIZE;
  const reviewListParams = useMemo(
    () => ({ status: "pending_review" as const, page, page_size: pageSize }),
    [page, pageSize]
  );
  const { data, isLoading, isError, isFetching, refetch } =
    useAgentRepositoryListings(reviewListParams, isAdmin && active);
  const updateStatusMutation = useUpdateAgentRepositoryStatus();
  const listings = data?.items ?? [];
  const total = data?.pagination?.total ?? 0;
  const updatingRepositoryId = updateStatusMutation.isPending
    ? (updateStatusMutation.variables?.agentRepositoryId ?? null)
    : null;
  const [detailListing, setDetailListing] =
    useState<AgentRepositoryListingItem | null>(null);
  const {
    detail,
    repositoryDetail,
    isLoading: isDetailLoading,
    isError: isDetailError,
    isFetching: isDetailFetching,
    retry: refetchDetail,
  } = useRepositoryAgentDetail(detailListing, active);
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
      await updateStatusMutation.mutateAsync({
        agentRepositoryId: reviewListing.agent_repository_id,
        status: isApprove ? "shared" : "rejected",
        content,
      });
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
          <Button type="primary" onClick={() => refetch()} loading={isFetching}>
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
            onDetailClick={(listing) => setDetailListing(listing)}
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
            open={active && reviewAction != null && reviewListing != null}
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
                onClick={() => setPage(Math.max(1, page - 1))}
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
                    onClick={() => setPage(pageNumber)}
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
                onClick={() => setPage(Math.min(totalPages, page + 1))}
                aria-label={t("repository.pagination.next")}
              >
                <ChevronRight className="size-4" aria-hidden />
              </Button>
            </div>
          ) : null}
        </>
      )}
      <AgentDetail
        open={active && detailListing != null}
        onClose={() => setDetailListing(null)}
        detail={detail}
        agentIcon={
          detailListing ? (
            <RepositoryAgentIcon
              agentId={repositoryDetail?.agent_id ?? detailListing.agent_id}
              iconUrl={repositoryDetail?.icon_url ?? detailListing.icon_url}
              size={48}
              iconSize={24}
            />
          ) : undefined
        }
        published
        status={repositoryDetail?.status}
        showRepositoryInfo
        isLoading={isDetailLoading}
        isError={isDetailError}
        isFetching={isDetailFetching}
        onRetry={refetchDetail}
      />
    </div>
  );
}
