"use client";

import { useEffect, useMemo, useState } from "react";
import { App } from "antd";
import { useTranslation } from "react-i18next";
import {
  useSkillRepositoryListingDetail,
  useSkillRepositoryListings,
  useUpdateSkillRepositoryStatus,
} from "@/hooks/skillRepository/useSkillRepositoryListings";
import type {
  SkillRepositoryListingItem,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";
import { SkillDetail } from "@/components/skill/skill-detail";
import { ReviewSkillList } from "./components/ReviewSkillList";
import {
  SkillRepositoryReviewConfirmModal,
  type SkillRepositoryReviewAction,
} from "./components/SkillRepositoryReviewConfirmModal";
import { getSkillRepositoryStatusLabel } from "./components/skillRepositoryShared";

const REVIEW_PAGE_SIZE = 10;
const STATUS_ACTION_LABEL_KEYS: Partial<
  Record<SkillRepositoryListingStatus, string>
> = {
  not_shared: "skillRepository.action.status.notShared",
  shared: "skillRepository.action.status.shared",
  rejected: "skillRepository.action.status.rejected",
};

export function ReviewCenter({ active }: { active: boolean }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [reviewPage, setReviewPage] = useState(1);
  const [detailRepositoryId, setDetailRepositoryId] = useState<number | null>(
    null
  );
  const [reviewListing, setReviewListing] =
    useState<SkillRepositoryListingItem | null>(null);
  const [reviewAction, setReviewAction] =
    useState<SkillRepositoryReviewAction | null>(null);
  const reviewParams = useMemo(
    () => ({
      status: "pending_review" as const,
      page: reviewPage,
      page_size: REVIEW_PAGE_SIZE,
      sort_by_update_time: true,
    }),
    [reviewPage]
  );
  const {
    data: reviewData,
    isLoading: isReviewLoading,
    isError: isReviewError,
    isFetching: isReviewFetching,
    refetch: refetchReview,
  } = useSkillRepositoryListings(reviewParams, active);
  const updateStatusMutation = useUpdateSkillRepositoryStatus();
  const {
    data: detailData,
    isLoading: isDetailLoading,
    isError: isDetailError,
    isFetching: isDetailFetching,
    refetch: refetchDetail,
  } = useSkillRepositoryListingDetail(
    detailRepositoryId,
    detailRepositoryId != null
  );
  const reviewItems = reviewData?.items ?? [];
  const reviewTotal = reviewData?.pagination?.total ?? 0;
  const updatingRepositoryId = updateStatusMutation.isPending
    ? (updateStatusMutation.variables?.skillRepositoryId ?? null)
    : null;

  useEffect(() => {
    if (active) refetchReview().catch(() => {});
  }, [active, refetchReview]);

  useEffect(() => {
    const total = reviewData?.pagination?.total;
    if (total == null) return;
    const totalPages = Math.max(1, Math.ceil(total / REVIEW_PAGE_SIZE));
    if (reviewPage > totalPages) {
      /* eslint-disable react-hooks/set-state-in-effect -- Clamp after server pagination changes. */
      setReviewPage(totalPages);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [reviewData?.pagination?.total, reviewPage]);

  const openDetail = (listing: SkillRepositoryListingItem) => {
    setDetailRepositoryId(listing.skill_repository_id);
  };

  const handleUpdateStatus = async (
    listing: SkillRepositoryListingItem,
    status: SkillRepositoryListingStatus,
    content?: string
  ) => {
    try {
      await updateStatusMutation.mutateAsync({
        skillRepositoryId: listing.skill_repository_id,
        status,
        content,
      });
      message.success(
        t("skillRepository.action.success", {
          action: STATUS_ACTION_LABEL_KEYS[status]
            ? t(STATUS_ACTION_LABEL_KEYS[status])
            : getSkillRepositoryStatusLabel(t, status),
        })
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("skillRepository.common.statusUpdateFailed")
      );
    }
  };
  const openReviewConfirmModal = (
    listing: SkillRepositoryListingItem,
    action: SkillRepositoryReviewAction
  ) => {
    setReviewListing(listing);
    setReviewAction(action);
  };

  const closeReviewConfirmModal = () => {
    setReviewListing(null);
    setReviewAction(null);
  };
  return (
    <>
      {active ? (
        <ReviewSkillList
          listings={reviewItems}
          isLoading={isReviewLoading}
          isError={isReviewError}
          isFetching={isReviewFetching}
          page={reviewPage}
          pageSize={REVIEW_PAGE_SIZE}
          total={reviewTotal}
          onPageChange={setReviewPage}
          onRetry={() => refetchReview()}
          updatingRepositoryId={updatingRepositoryId}
          onDetailClick={openDetail}
          onApprove={(listing) => openReviewConfirmModal(listing, "approve")}
          onReject={(listing) => openReviewConfirmModal(listing, "reject")}
        />
      ) : null}
      <SkillDetail
        open={detailRepositoryId != null}
        detail={detailData}
        isLoading={isDetailLoading}
        isError={isDetailError}
        isFetching={isDetailFetching}
        onClose={() => setDetailRepositoryId(null)}
        onRetry={() => refetchDetail()}
      />
      <SkillRepositoryReviewConfirmModal
        open={reviewAction != null && reviewListing != null}
        action={reviewAction}
        listing={reviewListing}
        loading={updateStatusMutation.isPending}
        onClose={closeReviewConfirmModal}
        onConfirm={async (content) => {
          if (!reviewListing || !reviewAction) {
            return;
          }
          await handleUpdateStatus(
            reviewListing,
            reviewAction === "approve" ? "shared" : "rejected",
            content
          );
          closeReviewConfirmModal();
        }}
      />
    </>
  );
}
