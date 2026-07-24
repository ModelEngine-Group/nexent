"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  App,
  Button,
  ConfigProvider,
  Empty,
  Input,
  Modal,
  Spin,
} from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Bot, ChevronLeft, ChevronRight, Inbox, Search, ShieldCheck, User } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import {
  useAgentRepositoryListingDetail,
  useAgentRepositoryListings,
  useMyEditableAgents,
  useUpdateAgentRepositoryStatus,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import { useAgentVersionDetail } from "@/hooks/agent/useAgentVersionDetail";
import {
  mapAgentVersionDetail,
  mapRepositoryListingDetail,
  type AgentDetailModalData,
} from "@/lib/agentRepositoryDetail";
import type { AgentRepositoryListingItem, MineOwnershipFilter } from "@/types/agentRepository";
import { isNewAgentPaddingItem } from "@/types/agentRepository";
import { parseReviewDeepLinkParams } from "@/lib/notificationNavigation";
import { cn } from "@/lib/utils";
import { AgentRepositoryCard } from "./components/AgentRepositoryCard";
import { AgentRepositoryCopyDialog } from "./components/AgentRepositoryCopyDialog";
import { AgentRepositoryDetailModal } from "./components/AgentRepositoryDetailModal";
import { MineAgentsView } from "./components/MineAgentsView";
import { ReviewAgentList } from "./components/ReviewAgentList";
import {
  AgentRepositoryReviewConfirmModal,
  type AgentRepositoryReviewAction,
} from "./components/AgentRepositoryReviewConfirmModal";

enum AgentRepositoryTab {
  REPOSITORY = "repository",
  MINE = "mine",
  REVIEW = "review",
}

const MINE_PAGE_SIZE = 6;
const REPOSITORY_PAGE_SIZE = 6;
const REVIEW_PAGE_SIZE = 10;

type AgentDetailSource =
  | { kind: "repository"; agentRepositoryId: number }
  | { kind: "mine"; agentId: number; versionNo: number };

const agentRepositoryTheme = {
  token: { colorPrimary: "#2563eb", colorInfo: "#3b82f6" },
};

export default function AgentRepositoryPage() {
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();
  const searchParams = useSearchParams();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const { user } = useAuthorizationContext();
  const isAdmin = user?.role === USER_ROLES.ADMIN;

  const [tab, setTab] = useState<AgentRepositoryTab>(() => {
    const backTab = searchParams.get("back_tab");
    if (backTab === "mine") return AgentRepositoryTab.MINE;
    if (backTab === "repository") return AgentRepositoryTab.REPOSITORY;
    if (backTab === "review") return AgentRepositoryTab.REVIEW;
    return AgentRepositoryTab.REPOSITORY;
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [repositoryPage, setRepositoryPage] = useState(1);
  const [mineOwnership, setMineOwnership] = useState<MineOwnershipFilter>("all");
  const [minePage, setMinePage] = useState(1);
  const [mineSearch, setMineSearch] = useState("");
  const [reviewPage, setReviewPage] = useState(1);
  const [detailSource, setDetailSource] = useState<AgentDetailSource | null>(
    null
  );
  const [copyOpen, setCopyOpen] = useState(false);
  const [copyListing, setCopyListing] = useState<AgentRepositoryListingItem | null>(null);

  useEffect(() => {
    const tabParam = searchParams.get("tab");
    if (tabParam === AgentRepositoryTab.MINE) {
      setTab(AgentRepositoryTab.MINE);
      return;
    }
    if (tabParam === AgentRepositoryTab.REPOSITORY) {
      setTab(AgentRepositoryTab.REPOSITORY);
      return;
    }
    if (tabParam === AgentRepositoryTab.REVIEW && isAdmin) {
      setTab(AgentRepositoryTab.REVIEW);
    }
  }, [searchParams, isAdmin]);

  const isRepositoryTab = tab === AgentRepositoryTab.REPOSITORY;
  const isReviewTab = tab === AgentRepositoryTab.REVIEW;
  const isMineTab = tab === AgentRepositoryTab.MINE;

  const reviewDeepLink = useMemo(
    () => parseReviewDeepLinkParams(searchParams),
    [searchParams]
  );

  const handleReviewDeepLinkConsumed = useCallback(() => {
    router.replace(`/${locale}/agent-space?tab=mine`);
  }, [locale, router]);

  const listingParams = useMemo(
    () => ({
      status: "shared" as const,
      page: repositoryPage,
      page_size: REPOSITORY_PAGE_SIZE,
      ...(searchQuery.trim() ? { search: searchQuery.trim() } : {}),
    }),
    [repositoryPage, searchQuery]
  );

  const { data, isLoading, isError, refetch, isFetching } =
    useAgentRepositoryListings(listingParams, isRepositoryTab);

  const { data: repositoryCountData } = useAgentRepositoryListings(
    { status: "shared", page: 1, page_size: 1 },
    true
  );

  const mineListParams = useMemo(
    () => ({
      ownership: mineOwnership,
      page: minePage,
      page_size: MINE_PAGE_SIZE,
      ...(mineSearch.trim() ? { search: mineSearch.trim() } : {}),
      ...(mineOwnership === "all" && !mineSearch.trim()
        ? { new_agent_padding: true }
        : {}),
    }),
    [mineOwnership, minePage, mineSearch]
  );

  const {
    data: mineData,
    isLoading: isMineLoading,
    isError: isMineError,
    isFetching: isMineFetching,
    refetch: refetchMine,
  } = useMyEditableAgents(mineListParams, isMineTab);

  const {
    data: deepLinkMineData,
    isLoading: isDeepLinkMineLoading,
  } = useMyEditableAgents(
    {
      ownership: "all",
      agent_id: reviewDeepLink?.agentId,
      page: 1,
      page_size: 1,
      new_agent_padding: false,
    },
    isMineTab && reviewDeepLink != null
  );

  const { data: mineCountData } = useMyEditableAgents(
    { page: 1, page_size: 1, ownership: "all" },
    true
  );

  const reviewListParams = useMemo(
    () => ({
      status: "pending_review" as const,
      page: reviewPage,
      page_size: REVIEW_PAGE_SIZE,
    }),
    [reviewPage]
  );

  const {
    data: reviewData,
    isLoading: isReviewLoading,
    isError: isReviewError,
    isFetching: isReviewFetching,
    refetch: refetchReview,
  } = useAgentRepositoryListings(reviewListParams, isAdmin && isReviewTab);

  const { data: reviewCountData } = useAgentRepositoryListings(
    { status: "pending_review", page: 1, page_size: 1 },
    isAdmin
  );

  const updateStatusMutation = useUpdateAgentRepositoryStatus();

  const detailOpen = detailSource !== null;
  const selectedRepositoryId =
    detailSource?.kind === "repository" ? detailSource.agentRepositoryId : null;
  const mineDetailAgentId =
    detailSource?.kind === "mine" ? detailSource.agentId : null;
  const mineDetailVersionNo =
    detailSource?.kind === "mine" ? detailSource.versionNo : null;

  const {
    data: repositoryDetail,
    isLoading: isRepositoryDetailLoading,
    isError: isRepositoryDetailError,
    isFetching: isRepositoryDetailFetching,
    refetch: refetchRepositoryDetail,
  } = useAgentRepositoryListingDetail(
    selectedRepositoryId,
    detailOpen && detailSource?.kind === "repository"
  );

  const {
    data: mineVersionDetail,
    isLoading: isMineVersionDetailLoading,
    isError: isMineVersionDetailError,
    isFetching: isMineVersionDetailFetching,
    refetch: refetchMineVersionDetail,
  } = useAgentVersionDetail(
    mineDetailAgentId,
    mineDetailVersionNo,
    detailOpen && detailSource?.kind === "mine"
  );

  const detail: AgentDetailModalData | null | undefined = useMemo(() => {
    if (detailSource?.kind === "repository" && repositoryDetail) {
      return mapRepositoryListingDetail(repositoryDetail);
    }
    if (detailSource?.kind === "mine" && mineVersionDetail) {
      return mapAgentVersionDetail(mineVersionDetail);
    }
    return detailSource ? undefined : null;
  }, [detailSource, repositoryDetail, mineVersionDetail]);

  const isDetailLoading =
    detailSource?.kind === "repository"
      ? isRepositoryDetailLoading
      : detailSource?.kind === "mine"
        ? isMineVersionDetailLoading
        : false;

  const isDetailError =
    detailSource?.kind === "repository"
      ? isRepositoryDetailError
      : detailSource?.kind === "mine"
        ? isMineVersionDetailError
        : false;

  const isDetailFetching =
    detailSource?.kind === "repository"
      ? isRepositoryDetailFetching
      : detailSource?.kind === "mine"
        ? isMineVersionDetailFetching
        : false;

  const refetchDetail = () => {
    if (detailSource?.kind === "repository") {
      refetchRepositoryDetail().catch(() => {});
      return;
    }
    if (detailSource?.kind === "mine") {
      refetchMineVersionDetail().catch(() => {});
    }
  };

  const handleDetailClick = (listing: AgentRepositoryListingItem) => {
    setDetailSource({
      kind: "repository",
      agentRepositoryId: listing.agent_repository_id,
    });
  };

  const handleMineViewDetail = (agentId: number, versionNo: number) => {
    setDetailSource({ kind: "mine", agentId, versionNo });
  };

  const handleDetailClose = () => {
    setDetailSource(null);
  };

  const handleCopyClick = (listing: AgentRepositoryListingItem) => {
    setCopyListing(listing);
    setCopyOpen(true);
  };

  const handleCopyClose = () => {
    setCopyOpen(false);
    setCopyListing(null);
  };

  const handleRepositoryTakeDown = (listing: AgentRepositoryListingItem) =>
    updateStatusMutation.mutateAsync({
      agentRepositoryId: listing.agent_repository_id,
      status: "not_shared",
    });

  const updatingRepositoryId =
    updateStatusMutation.isPending
      ? updateStatusMutation.variables?.agentRepositoryId ?? null
      : null;

  const listings = data?.items ?? [];
  const repositoryPagination = data?.pagination;
  const repositoryTotal = repositoryPagination?.total ?? 0;
  const reviewListings = reviewData?.items ?? [];
  const reviewPagination = reviewData?.pagination;
  const reviewTotal = reviewPagination?.total ?? 0;
  const mineAgents = mineData?.items ?? [];
  const mineCounts = mineData?.counts ?? { all: 0, created: 0, others: 0 };
  const minePagination = mineData?.pagination;
  const mineTotal = minePagination?.total ?? 0;
  const deepLinkFallbackAgent = useMemo(() => {
    const item = deepLinkMineData?.items?.[0];
    if (!item || isNewAgentPaddingItem(item)) {
      return null;
    }
    return item;
  }, [deepLinkMineData]);
  const repositoryTabCount = repositoryCountData?.pagination?.total ?? 0;
  const mineTabCount = mineCountData?.counts?.all ?? 0;
  const pendingReviewCount = reviewCountData?.pagination?.total ?? 0;

  const handleRepositorySearchChange = (value: string) => {
    setSearchQuery(value);
    setRepositoryPage(1);
  };

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

              <Tabs
                value={tab}
                onValueChange={(value) => setTab(value as AgentRepositoryTab)}
                className="w-full"
              >
                <TabsList
                  className={cn(
                    "mb-6 grid h-auto w-full gap-2 rounded-xl border border-border bg-secondary/60 px-2 py-2",
                    isAdmin ? "grid-cols-3" : "grid-cols-2"
                  )}
                >
                  <TabsTrigger
                    value={AgentRepositoryTab.REPOSITORY}
                    className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                  >
                    <Inbox className="size-4" aria-hidden />
                    {t("agentRepository.page.tab.repository")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">
                      {repositoryTabCount}
                    </span>
                  </TabsTrigger>
                  <TabsTrigger
                    value={AgentRepositoryTab.MINE}
                    className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                  >
                    <User className="size-4" aria-hidden />
                    {t("agentRepository.page.tab.mine")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">
                      {mineTabCount}
                    </span>
                  </TabsTrigger>
                  {isAdmin ? (
                    <TabsTrigger
                      value={AgentRepositoryTab.REVIEW}
                      className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                    >
                      <ShieldCheck className="size-4" aria-hidden />
                      {t("agentRepository.page.tab.review")}
                      {pendingReviewCount > 0 ? (
                        <span className="ml-1 inline-flex size-5 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                          {pendingReviewCount}
                        </span>
                      ) : null}
                    </TabsTrigger>
                  ) : null}
                </TabsList>
              </Tabs>

              {isRepositoryTab ? (
                <RepositoryView
                  searchQuery={searchQuery}
                  onSearchChange={handleRepositorySearchChange}
                  isLoading={isLoading}
                  isError={isError}
                  isFetching={isFetching}
                  onRetry={() => refetch()}
                  listings={listings}
                  page={repositoryPage}
                  pageSize={REPOSITORY_PAGE_SIZE}
                  total={repositoryTotal}
                  onPageChange={setRepositoryPage}
                  onCopyClick={handleCopyClick}
                  onDetailClick={handleDetailClick}
                  showAdminMenu={isAdmin}
                  updatingRepositoryId={updatingRepositoryId}
                  onTakeDown={handleRepositoryTakeDown}
                />
              ) : isReviewTab ? (
                <ReviewCenterView
                  listings={reviewListings}
                  currentUserEmail={user?.email}
                  isLoading={isReviewLoading}
                  isError={isReviewError}
                  isFetching={isReviewFetching}
                  onRetry={() => refetchReview()}
                  page={reviewPage}
                  pageSize={REVIEW_PAGE_SIZE}
                  total={reviewTotal}
                  onPageChange={setReviewPage}
                  updatingRepositoryId={updatingRepositoryId}
                  onDetailClick={handleDetailClick}
                  onApprove={(listing, content) =>
                    updateStatusMutation.mutateAsync({
                      agentRepositoryId: listing.agent_repository_id,
                      status: "shared",
                      content,
                    })
                  }
                  onReject={(listing, content) =>
                    updateStatusMutation.mutateAsync({
                      agentRepositoryId: listing.agent_repository_id,
                      status: "rejected",
                      content,
                    })
                  }
                />
              ) : isMineTab ? (
                <MineAgentsView
                  agents={mineAgents}
                  counts={mineCounts}
                  ownership={mineOwnership}
                  onOwnershipChange={(ownership) => {
                    setMineOwnership(ownership);
                    setMinePage(1);
                  }}
                  searchQuery={mineSearch}
                  onSearchChange={(value) => {
                    setMineSearch(value);
                    setMinePage(1);
                  }}
                  page={minePage}
                  pageSize={MINE_PAGE_SIZE}
                  total={mineTotal}
                  onPageChange={setMinePage}
                  isLoading={isMineLoading}
                  isError={isMineError}
                  isFetching={isMineFetching}
                  onRetry={() => refetchMine()}
                  onViewDetail={handleMineViewDetail}
                  reviewDeepLink={reviewDeepLink}
                  deepLinkFallbackAgent={deepLinkFallbackAgent}
                  deepLinkFallbackLoading={isDeepLinkMineLoading}
                  onReviewDeepLinkConsumed={handleReviewDeepLinkConsumed}
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
      <AgentRepositoryCopyDialog
        listing={copyListing}
        open={copyOpen}
        onOpenChange={(open) => {
          if (!open) {
            handleCopyClose();
          } else {
            setCopyOpen(true);
          }
        }}
      />
    </ConfigProvider>
  );
}

function RepositoryView({
  searchQuery,
  onSearchChange,
  isLoading,
  isError,
  isFetching,
  onRetry,
  listings,
  page,
  pageSize,
  total,
  onPageChange,
  onCopyClick,
  onDetailClick,
  showAdminMenu,
  updatingRepositoryId,
  onTakeDown,
}: {
  searchQuery: string;
  onSearchChange: (value: string) => void;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onRetry: () => void;
  listings: AgentRepositoryListingItem[];
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onCopyClick: (listing: AgentRepositoryListingItem) => void;
  onDetailClick: (listing: AgentRepositoryListingItem) => void;
  showAdminMenu: boolean;
  updatingRepositoryId: number | null;
  onTakeDown: (listing: AgentRepositoryListingItem) => Promise<unknown>;
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 0;
  const showPagination = !isLoading && !isError && totalPages > 1;

  const getListingTitle = (listing: AgentRepositoryListingItem) =>
    listing.display_name?.trim() ||
    listing.name?.trim() ||
    t("agentRepository.card.untitled");

  const confirmTakeDown = (listing: AgentRepositoryListingItem) => {
    const title = getListingTitle(listing);

    Modal.confirm({
      title: t("agentRepository.mine.reviewModal.confirmTakeDownTitle"),
      content: t("agentRepository.mine.reviewModal.confirmTakeDownContent", {
        name: title,
      }),
      okText: t("agentRepository.mine.reviewModal.takeDown"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await onTakeDown(listing);
          message.success(t("agentRepository.mine.takeDownSuccess"));
        } catch {
          message.error(t("agentRepository.mine.takeDownError"));
          throw new Error("Take down failed");
        }
      },
    });
  };

  return (
    <div className="space-y-5">
      <div className="relative">
        <Input
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={t("agentRepository.page.searchPlaceholder")}
          prefix={<Search className="size-4 text-slate-400" aria-hidden />}
          className="h-11 rounded-xl"
          allowClear
        />
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
        <>
          <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {listings.map((listing) => (
              <div key={listing.agent_repository_id} className="h-full">
                <AgentRepositoryCard
                  listing={listing}
                  showAdminMenu={showAdminMenu}
                  isTakingDown={updatingRepositoryId === listing.agent_repository_id}
                  onCopyClick={onCopyClick}
                  onDetailClick={onDetailClick}
                  onTakeDown={() => confirmTakeDown(listing)}
                />
              </div>
            ))}
          </div>

          {showPagination ? (
            <div className="flex items-center justify-center gap-1.5 pt-2">
              <Button
                type="default"
                className="flex size-9 items-center justify-center rounded-lg p-0"
                disabled={page <= 1}
                onClick={() => onPageChange(Math.max(1, page - 1))}
                aria-label={t("agentRepository.mine.pagination.prev")}
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
                    aria-label={t("agentRepository.mine.pagination.page", {
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
                aria-label={t("agentRepository.mine.pagination.next")}
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

function ReviewCenterView({
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
}: {
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
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [reviewAction, setReviewAction] =
    useState<AgentRepositoryReviewAction | null>(null);
  const [reviewListing, setReviewListing] =
    useState<AgentRepositoryListingItem | null>(null);

  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 0;
  const showPagination = !isLoading && !isError && totalPages > 1;

  const getListingTitle = (listing: AgentRepositoryListingItem) =>
    listing.display_name?.trim() ||
    listing.name?.trim() ||
    t("agentRepository.card.untitled");

  const closeReviewModal = () => {
    setReviewAction(null);
    setReviewListing(null);
  };

  const openReviewModal = (
    listing: AgentRepositoryListingItem,
    action: AgentRepositoryReviewAction
  ) => {
    setReviewListing(listing);
    setReviewAction(action);
  };

  const handleReviewConfirm = async (content?: string) => {
    if (!reviewListing || !reviewAction) {
      return;
    }

    const title = getListingTitle(reviewListing);
    const isApprove = reviewAction === "approve";

    try {
      await (isApprove
        ? onApprove(reviewListing, content)
        : onReject(reviewListing, content));
      message.success(
        isApprove
          ? t("agentRepository.review.approveSuccess", { name: title })
          : t("agentRepository.review.rejectSuccess", { name: title })
      );
      closeReviewModal();
    } catch {
      message.error(
        isApprove
          ? t("agentRepository.review.approveError")
          : t("agentRepository.review.rejectError")
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
            {t("agentRepository.review.loadError")}
          </p>
          <Button type="primary" onClick={onRetry} loading={isFetching}>
            {t("agentRepository.page.retry")}
          </Button>
        </div>
      ) : listings.length === 0 ? (
        <Empty className="py-16" description={t("agentRepository.review.empty")} />
      ) : (
        <>
          <ReviewAgentList
            listings={listings}
            currentUserEmail={currentUserEmail}
            updatingRepositoryId={updatingRepositoryId}
            onDetailClick={onDetailClick}
            onApprove={(listing) => openReviewModal(listing, "approve")}
            onReject={(listing) => openReviewModal(listing, "reject")}
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
                aria-label={t("agentRepository.mine.pagination.prev")}
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
                    aria-label={t("agentRepository.mine.pagination.page", {
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
                aria-label={t("agentRepository.mine.pagination.next")}
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
