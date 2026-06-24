"use client";

import { useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  ConfigProvider,
  Empty,
  Input,
  Modal,
  Segmented,
  Spin,
} from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Bot, Check, Clock, Inbox, Search, ShieldCheck, User, X } from "lucide-react";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import {
  useAgentRepositoryOptions,
  useAgentRepositoryListingDetail,
  useAgentRepositoryListings,
  useMyEditableAgents,
  useUpdateAgentRepositoryStatus,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import type { AgentRepositoryCategoryItem, AgentRepositoryListingItem, MineOwnershipFilter } from "@/types/agentRepository";
import { AgentRepositoryCard } from "./components/AgentRepositoryCard";
import { AgentRepositoryDetailModal } from "./components/AgentRepositoryDetailModal";
import { MineAgentsView } from "./components/MineAgentsView";

enum AgentRepositoryTab {
  REPOSITORY = "repository",
  MINE = "mine",
  REVIEW = "review",
}

const agentRepositoryTheme = {
  token: { colorPrimary: "#2563eb", colorInfo: "#3b82f6" },
};

export default function AgentRepositoryPage() {
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();
  const { user } = useAuthorizationContext();
  const isAdmin = user?.role === USER_ROLES.ADMIN;

  const [tab, setTab] = useState<AgentRepositoryTab>(AgentRepositoryTab.REPOSITORY);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [mineOwnership, setMineOwnership] = useState<MineOwnershipFilter>("all");
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedRepositoryId, setSelectedRepositoryId] = useState<number | null>(null);

  const isRepositoryTab = tab === AgentRepositoryTab.REPOSITORY;
  const isReviewTab = tab === AgentRepositoryTab.REVIEW;
  const isMineTab = tab === AgentRepositoryTab.MINE;

  const { data: categories = [] } = useAgentRepositoryOptions(
    "categories",
    isRepositoryTab || isReviewTab
  );

  const categoryNameById = useMemo(
    () => new Map(categories.map((item) => [item.id, item.name])),
    [categories]
  );

  const listingParams = {
    status: "shared" as const,
    ...(selectedCategoryId == null ? {} : { category_id: selectedCategoryId }),
  };

  const { data, isLoading, isError, refetch, isFetching } =
    useAgentRepositoryListings(listingParams, isRepositoryTab);

  const {
    data: mineData,
    isLoading: isMineLoading,
    isError: isMineError,
    isFetching: isMineFetching,
    refetch: refetchMine,
  } = useMyEditableAgents(mineOwnership, isMineTab);

  const {
    data: reviewData,
    isLoading: isReviewLoading,
    isError: isReviewError,
    isFetching: isReviewFetching,
    refetch: refetchReview,
  } = useAgentRepositoryListings(
    { status: "pending_review", deduplicate_by_agent_id: false },
    isAdmin && isReviewTab
  );

  const updateStatusMutation = useUpdateAgentRepositoryStatus();

  const {
    data: detail,
    isLoading: isDetailLoading,
    isError: isDetailError,
    isFetching: isDetailFetching,
    refetch: refetchDetail,
  } = useAgentRepositoryListingDetail(selectedRepositoryId, detailOpen);

  const handleDetailClick = (listing: AgentRepositoryListingItem) => {
    setSelectedRepositoryId(listing.agent_repository_id);
    setDetailOpen(true);
  };

  const handleDetailClose = () => {
    setDetailOpen(false);
    setSelectedRepositoryId(null);
  };

  const listings = data?.items ?? [];
  const reviewListings = reviewData?.items ?? [];
  const mineAgents = mineData?.items ?? [];
  const mineCounts = mineData?.counts ?? { all: 0, created: 0, others: 0 };
  const pendingReviewCount = reviewListings.length;

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filteredListings = normalizedQuery
    ? listings.filter((item) => {
        const title = (item.display_name || item.name || "").toLowerCase();
        const author = (item.author || "").toLowerCase();
        const description = (item.description || "").toLowerCase();
        const tags = (item.tags || [])
          .map((tag) => tag.toLowerCase())
          .join(" ");
        return (
          title.includes(normalizedQuery) ||
          author.includes(normalizedQuery) ||
          description.includes(normalizedQuery) ||
          tags.includes(normalizedQuery)
        );
      })
    : listings;

  const tabOptions = [
    {
      value: AgentRepositoryTab.REPOSITORY,
      label: (
        <span className="inline-flex items-center gap-1.5 text-sm">
          <Inbox className="size-4" aria-hidden />
          {t("agentRepository.page.tab.repository")}
        </span>
      ),
    },
    {
      value: AgentRepositoryTab.MINE,
      label: (
        <span className="inline-flex items-center gap-1.5 text-sm">
          <User className="size-4" aria-hidden />
          {t("agentRepository.page.tab.mine")}
        </span>
      ),
    },
    ...(isAdmin
      ? [
          {
            value: AgentRepositoryTab.REVIEW,
            label: (
              <span className="inline-flex items-center gap-1.5 text-sm">
                <ShieldCheck className="size-4" aria-hidden />
                {t("agentRepository.page.tab.review")}
                {pendingReviewCount > 0 ? (
                  <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-primary px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white">
                    {pendingReviewCount}
                  </span>
                ) : null}
              </span>
            ),
          },
        ]
      : []),
  ];

  return (
    <ConfigProvider theme={agentRepositoryTheme}>
      <div className="flex h-full min-h-0 w-full min-w-0 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
          <motion.div
            initial="initial"
            animate="in"
            exit="out"
            variants={pageVariants}
            transition={pageTransition}
            className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 sm:py-10"
          >
            <div className="flex flex-col gap-6">
              <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex items-start gap-4">
                  <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-sm">
                    <Bot className="size-7" />
                  </div>
                  <div>
                    <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl dark:text-slate-100">
                      {t("agentRepository.page.title")}
                    </h1>
                    <p className="mt-1 max-w-xl text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                      {t("agentRepository.page.subtitle")}
                    </p>
                  </div>
                </div>
              </section>

              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <Segmented
                  value={tab}
                  onChange={(value) => setTab(value as AgentRepositoryTab)}
                  options={tabOptions}
                  className="h-9 w-full max-w-md rounded-md border border-slate-200 bg-slate-100 p-[2px] text-sm shadow-sm sm:w-auto"
                />
                {isRepositoryTab ? (
                  <span className="pb-0.5 text-xs text-slate-400 sm:shrink-0 sm:text-right">
                    {t("agentRepository.page.resultCount", {
                      count: filteredListings.length,
                    })}
                  </span>
                ) : isMineTab ? (
                  <span className="pb-0.5 text-xs text-slate-400 sm:shrink-0 sm:text-right">
                    {t("agentRepository.mine.resultCount", {
                      count: mineCounts[mineOwnership],
                    })}
                  </span>
                ) : null}
              </div>

              {isRepositoryTab ? (
                <RepositoryView
                  searchQuery={searchQuery}
                  onSearchChange={setSearchQuery}
                  categories={categories}
                  categoryNameById={categoryNameById}
                  selectedCategoryId={selectedCategoryId}
                  onCategoryChange={setSelectedCategoryId}
                  isLoading={isLoading}
                  isError={isError}
                  isFetching={isFetching}
                  onRetry={() => refetch()}
                  listings={filteredListings}
                  onDetailClick={handleDetailClick}
                />
              ) : isReviewTab ? (
                <ReviewCenterView
                  listings={reviewListings}
                  categoryNameById={categoryNameById}
                  isLoading={isReviewLoading}
                  isError={isReviewError}
                  isFetching={isReviewFetching}
                  onRetry={() => refetchReview()}
                  onDetailClick={handleDetailClick}
                  updatingRepositoryId={
                    updateStatusMutation.isPending
                      ? updateStatusMutation.variables?.agentRepositoryId ?? null
                      : null
                  }
                  onApprove={(listing) =>
                    updateStatusMutation.mutateAsync({
                      agentRepositoryId: listing.agent_repository_id,
                      status: "shared",
                    })
                  }
                  onReject={(listing) =>
                    updateStatusMutation.mutateAsync({
                      agentRepositoryId: listing.agent_repository_id,
                      status: "rejected",
                    })
                  }
                />
              ) : isMineTab ? (
                <MineAgentsView
                  agents={mineAgents}
                  counts={mineCounts}
                  ownership={mineOwnership}
                  onOwnershipChange={setMineOwnership}
                  isLoading={isMineLoading}
                  isError={isMineError}
                  isFetching={isMineFetching}
                  onRetry={() => refetchMine()}
                />
              ) : null}
            </div>
          </motion.div>
        </div>
      </div>
      <AgentRepositoryDetailModal
        open={detailOpen}
        onClose={handleDetailClose}
        detail={detail}
        isLoading={isDetailLoading}
        isError={isDetailError}
        isFetching={isDetailFetching}
        onRetry={() => refetchDetail()}
      />
    </ConfigProvider>
  );
}

function RepositoryView({
  searchQuery,
  onSearchChange,
  categories,
  categoryNameById,
  selectedCategoryId,
  onCategoryChange,
  isLoading,
  isError,
  isFetching,
  onRetry,
  listings,
  onDetailClick,
}: {
  searchQuery: string;
  onSearchChange: (value: string) => void;
  categories: AgentRepositoryCategoryItem[];
  categoryNameById: Map<number, string>;
  selectedCategoryId: number | null;
  onCategoryChange: (categoryId: number | null) => void;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onRetry: () => void;
  listings: AgentRepositoryListingItem[];
  onDetailClick: (listing: AgentRepositoryListingItem) => void;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="space-y-5">
      <div className="relative">
        <Search className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
        <Input
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={t("agentRepository.page.searchPlaceholder")}
          className="h-11 rounded-xl pl-10"
          allowClear
        />
      </div>

      <div className="flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => onCategoryChange(null)}
          className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
            selectedCategoryId == null
              ? "bg-primary text-white"
              : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          }`}
        >
          {t("agentRepository.page.categoryAll")}
        </button>
        {categories.map((category) => (
          <button
            key={category.id}
            type="button"
            onClick={() => onCategoryChange(category.id)}
            className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
              selectedCategoryId === category.id
                ? "bg-primary text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            }`}
          >
            {category.name}
          </button>
        ))}
      </div>

      <p className="text-sm text-slate-500 dark:text-slate-400">
        {t("agentRepository.page.repositoryHint")}
      </p>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-200 py-16 text-center dark:border-slate-700">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("agentRepository.page.loadError")}
          </p>
          <Button type="primary" onClick={onRetry} loading={isFetching}>
            {t("agentRepository.page.retry")}
          </Button>
        </div>
      ) : listings.length === 0 ? (
        <Empty
          className="py-16"
          description={t("agentRepository.page.empty")}
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {listings.map((listing) => (
            <AgentRepositoryCard
              key={listing.agent_repository_id}
              listing={listing}
              categoryName={
                listing.category_id != null
                  ? categoryNameById.get(listing.category_id)
                  : undefined
              }
              onDetailClick={onDetailClick}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ReviewCenterView({
  listings,
  categoryNameById,
  isLoading,
  isError,
  isFetching,
  onRetry,
  onDetailClick,
  updatingRepositoryId,
  onApprove,
  onReject,
}: {
  listings: AgentRepositoryListingItem[];
  categoryNameById: Map<number, string>;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onRetry: () => void;
  onDetailClick: (listing: AgentRepositoryListingItem) => void;
  updatingRepositoryId: number | null;
  onApprove: (listing: AgentRepositoryListingItem) => Promise<unknown>;
  onReject: (listing: AgentRepositoryListingItem) => Promise<unknown>;
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const getListingTitle = (listing: AgentRepositoryListingItem) =>
    listing.display_name?.trim() ||
    listing.name?.trim() ||
    t("agentRepository.card.untitled");

  const confirmReviewAction = (
    listing: AgentRepositoryListingItem,
    action: "approve" | "reject"
  ) => {
    const title = getListingTitle(listing);
    const isApprove = action === "approve";

    Modal.confirm({
      title: isApprove
        ? t("agentRepository.review.confirmApproveTitle")
        : t("agentRepository.review.confirmRejectTitle"),
      content: isApprove
        ? t("agentRepository.review.confirmApproveContent", { name: title })
        : t("agentRepository.review.confirmRejectContent", { name: title }),
      okText: isApprove
        ? t("agentRepository.review.approve")
        : t("agentRepository.review.reject"),
      cancelText: t("common.cancel"),
      okButtonProps: isApprove
        ? undefined
        : { danger: true },
      onOk: async () => {
        try {
          await (isApprove ? onApprove(listing) : onReject(listing));
          message.success(
            isApprove
              ? t("agentRepository.review.approveSuccess", { name: title })
              : t("agentRepository.review.rejectSuccess", { name: title })
          );
        } catch {
          message.error(
            isApprove
              ? t("agentRepository.review.approveError")
              : t("agentRepository.review.rejectError")
          );
          throw new Error("Review action failed");
        }
      },
    });
  };

  return (
    <div className="space-y-6">
      <Card className="rounded-xl border border-slate-200 shadow-sm dark:border-slate-700">
        <div className="flex items-center gap-2">
          <ShieldCheck className="size-5 text-primary" aria-hidden />
          <h2 className="font-semibold text-slate-900 dark:text-slate-100">
            {t("agentRepository.review.title")}
          </h2>
          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {t("agentRepository.review.pendingCount", { count: listings.length })}
          </span>
        </div>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {t("agentRepository.review.description")}
        </p>
      </Card>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-200 py-16 text-center dark:border-slate-700">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("agentRepository.review.loadError")}
          </p>
          <Button type="primary" onClick={onRetry} loading={isFetching}>
            {t("agentRepository.page.retry")}
          </Button>
        </div>
      ) : listings.length === 0 ? (
        <Empty className="py-16" description={t("agentRepository.review.empty")} />
      ) : (
        <div className="space-y-3">
          {listings.map((listing) => {
            const title = getListingTitle(listing);
            const isUpdating =
              updatingRepositoryId === listing.agent_repository_id;
            const submitter =
              listing.submitted_by?.trim() ||
              t("agentRepository.review.unknownSubmitter");
            const categoryName =
              listing.category_id != null
                ? categoryNameById.get(listing.category_id) ??
                  t("agentRepository.review.unknownCategory")
                : t("agentRepository.review.unknownCategory");

            return (
              <Card
                key={listing.agent_repository_id}
                className="rounded-xl border border-slate-200 p-4 shadow-sm dark:border-slate-700"
              >
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-2xl text-primary">
                      {listing.icon?.trim() ? (
                        <span aria-hidden>{listing.icon.trim()}</span>
                      ) : (
                        <Bot className="size-6" aria-hidden />
                      )}
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate font-semibold text-slate-900 dark:text-slate-100">
                          {title}
                        </h3>
                        <span className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-300">
                          <Clock className="size-3" aria-hidden />
                          {t("agentRepository.detail.status.pending_review")}
                        </span>
                      </div>
                      <p className="truncate text-sm text-slate-500 dark:text-slate-400">
                        {listing.description?.trim() ||
                          t("agentRepository.card.noDescription")}
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {t("agentRepository.review.submitter", { name: submitter })}
                        {" 路 "}
                        {categoryName}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <Button
                      type="default"
                      onClick={() => onDetailClick(listing)}
                      disabled={isUpdating}
                    >
                      {t("agentRepository.review.viewDetail")}
                    </Button>
                    <Button
                      danger
                      icon={<X className="size-4" aria-hidden />}
                      onClick={() => confirmReviewAction(listing, "reject")}
                      loading={isUpdating}
                      disabled={isUpdating}
                    >
                      {t("agentRepository.review.reject")}
                    </Button>
                    <Button
                      type="primary"
                      icon={<Check className="size-4" aria-hidden />}
                      onClick={() => confirmReviewAction(listing, "approve")}
                      loading={isUpdating}
                      disabled={isUpdating}
                    >
                      {t("agentRepository.review.approve")}
                    </Button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
