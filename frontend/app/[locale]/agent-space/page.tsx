"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ConfigProvider } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Bot, Inbox, ShieldCheck, User } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import { getTagSearchPredicates } from "@/lib/systemTagLabels";
import type {
  TagDefinition,
  TagResourcePredicate,
} from "@/types/tagManagement";
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
import type {
  AgentRepositoryListingItem,
  MineOwnershipFilter,
} from "@/types/agentRepository";
import { isNewAgentPaddingItem } from "@/types/agentRepository";
import { parseReviewDeepLinkParams } from "@/lib/notificationNavigation";
import { AgentRepositoryCopyDialog } from "./components/AgentRepositoryCopyDialog";
import { AgentRepositoryDetailModal } from "./components/AgentRepositoryDetailModal";
import { AgentSpace } from "./agent-space";
import { MyAgent } from "./my-agent";
import { ReviewCenter } from "./review-center";

enum AgentRepositoryTab {
  REPOSITORY = "repository",
  MINE = "mine",
  REVIEW = "review",
}

const MINE_PAGE_SIZE = 12;
const REPOSITORY_PAGE_SIZE = 12;
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
  const [repositoryTagPredicates, setRepositoryTagPredicates] = useState<
    TagResourcePredicate[]
  >([]);
  const [repositoryPage, setRepositoryPage] = useState(1);
  const [mineOwnership, setMineOwnership] =
    useState<MineOwnershipFilter>("all");
  const [minePage, setMinePage] = useState(1);
  const [mineSearch, setMineSearch] = useState("");
  const [mineTagPredicates, setMineTagPredicates] = useState<
    TagResourcePredicate[]
  >([]);
  const [reviewPage, setReviewPage] = useState(1);
  const [detailSource, setDetailSource] = useState<AgentDetailSource | null>(
    null
  );
  const [copyOpen, setCopyOpen] = useState(false);
  const [copyListing, setCopyListing] =
    useState<AgentRepositoryListingItem | null>(null);

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
  const { data: tagLibraries } = useTagLibraries();
  const defaultTagLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: mineTagDefinitions } = useTagDefinitions(
    defaultTagLibrary?.bucket_id ?? null
  );
  const repositorySearchTagPredicates = useMemo(
    () => getTagSearchPredicates(mineTagDefinitions, searchQuery, t),
    [mineTagDefinitions, searchQuery, t]
  );
  const mineSearchTagPredicates = useMemo(
    () => getTagSearchPredicates(mineTagDefinitions, mineSearch, t),
    [mineSearch, mineTagDefinitions, t]
  );

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
      ...(repositorySearchTagPredicates.length > 0
        ? { search_tag_predicates: repositorySearchTagPredicates }
        : {}),
      ...(repositoryTagPredicates.length > 0
        ? { tag_predicates: repositoryTagPredicates }
        : {}),
    }),
    [
      repositoryPage,
      repositorySearchTagPredicates,
      repositoryTagPredicates,
      searchQuery,
    ]
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
      ...(mineTagPredicates.length > 0
        ? { tag_predicates: mineTagPredicates }
        : {}),
      ...(mineSearchTagPredicates.length > 0
        ? { search_tag_predicates: mineSearchTagPredicates }
        : {}),
      ...(mineOwnership === "all" &&
      !mineSearch.trim() &&
      mineTagPredicates.length === 0
        ? { new_agent_padding: true }
        : {}),
    }),
    [
      mineOwnership,
      minePage,
      mineSearch,
      mineSearchTagPredicates,
      mineTagPredicates,
    ]
  );

  const {
    data: mineData,
    isLoading: isMineLoading,
    isError: isMineError,
    isFetching: isMineFetching,
    refetch: refetchMine,
  } = useMyEditableAgents(mineListParams, isMineTab);

  const { data: deepLinkMineData, isLoading: isDeepLinkMineLoading } =
    useMyEditableAgents(
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

  const updatingRepositoryId = updateStatusMutation.isPending
    ? (updateStatusMutation.variables?.agentRepositoryId ?? null)
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
            className="w-full px-4 py-8 sm:px-6 sm:py-10 xl:px-16"
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
                <TabsList className="mb-6 flex h-auto w-full justify-start gap-6 overflow-x-auto rounded-none border-b border-slate-200 bg-transparent p-0 dark:border-slate-700">
                  <TabsTrigger
                    value={AgentRepositoryTab.REPOSITORY}
                    className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
                  >
                    <Inbox className="size-4" aria-hidden />
                    {t("repository.page.tab.repository")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">
                      {repositoryTabCount}
                    </span>
                  </TabsTrigger>
                  <TabsTrigger
                    value={AgentRepositoryTab.MINE}
                    className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
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
                      className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
                    >
                      <ShieldCheck className="size-4" aria-hidden />
                      {t("repository.page.tab.review")}
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
                <AgentSpace
                  searchQuery={searchQuery}
                  onSearchChange={handleRepositorySearchChange}
                  tagDefinitions={mineTagDefinitions ?? []}
                  tagPredicates={repositoryTagPredicates}
                  onTagPredicatesChange={(value) => {
                    setRepositoryTagPredicates(value);
                    setRepositoryPage(1);
                  }}
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
                <ReviewCenter
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
                <MyAgent
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
                  tagDefinitions={mineTagDefinitions ?? []}
                  tagPredicates={mineTagPredicates}
                  onTagPredicatesChange={(value) => {
                    setMineTagPredicates(value);
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
