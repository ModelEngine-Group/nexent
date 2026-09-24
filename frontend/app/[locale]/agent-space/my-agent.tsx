"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Button, Empty, Grid, Input, Spin } from "antd";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import CreateAgentModal, {
  type CreatedAgentResult,
} from "@/components/agent/CreateAgentModal";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAgentList } from "@/hooks/agent/useAgentList";
import { useToolList } from "@/hooks/agent/useToolList";
import { useSkillList } from "@/hooks/agent/useSkillList";
import type { Agent } from "@/types/agentConfig";
import type { AgentListFilters } from "@/services/agentConfigService";
import { deleteAgent } from "@/services/agentConfigService";
import {
  AGENTS_LIST_QUERY_KEY,
  invalidateAgentRepositoryCaches,
  useCreateAgentRepositoryListing,
  useMyEditableAgents,
  useAgentRepositoryListings,
  useUpdateAgentRepositoryStatus,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import { getTagSearchPredicates } from "@/lib/systemTagLabels";
import { parseReviewDeepLinkParams } from "@/lib/notificationNavigation";
import log from "@/lib/logger";
import {
  isCancelableRepositoryStatus,
  isTakeDownableRepositoryStatus,
  findRepositoryInfoById,
  pickReviewDisplayRepositoryInfo,
  resolveReviewModalMode,
  toMineRepositoryInfo,
} from "@/lib/agentRepositoryMine";
import {
  isNewAgentPaddingItem,
  type AgentRepositoryListingCreatePayload,
  type MineOwnershipFilter,
  type MyAgentRepositoryInfoItem,
  type MyEditableAgentItem,
} from "@/types/agentRepository";
import { MineApplyListingModal } from "./components/MineApplyListingModal";
import { MineReviewStatusModal } from "./components/MineReviewStatusModal";
import { CreateNewAgentCard } from "./components/CreateNewAgentCard";
import { MyAgentCard } from "./components/MyAgentCard";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import TagFilterPopover from "@/components/tag/TagFilterPopover";
import type { TagResourcePredicate } from "@/types/tagManagement";
import { useAgentVersionDetail } from "@/hooks/agent/useAgentVersionDetail";
import { mapMyAgentDetail } from "@/lib/myAgentDetail";
import { AgentDetail } from "@/components/agent/agent-detail";
import { MyAgentIcon } from "./components/MyAgentIcon";

const MINE_OWNERSHIP_FILTERS: MineOwnershipFilter[] = [
  "all",
  "created",
  "others",
];
const CARD_GAP = 20;
const MIN_CARD_HEIGHT = 240;
const PAGINATION_HEIGHT = 60;

export function MyAgent({
  active,
  onTotalChange,
}: {
  active: boolean;
  onTotalChange?: (total: number) => void;
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();
  const { user } = useAuthorizationContext();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const screens = Grid.useBreakpoint();
  const gridRegionRef = useRef<HTMLDivElement>(null);
  const [availableGridHeight, setAvailableGridHeight] = useState<number | null>(
    null
  );
  const columns = screens.xxl
    ? 4
    : screens.xl
      ? 3
      : screens.lg || screens.md || screens.sm
        ? 2
        : screens.xs
          ? 1
          : 4;
  const pageBottomPadding = screens.sm ? 40 : 32;
  const rows = getRowCount(
    Math.max(0, (availableGridHeight ?? 0) - PAGINATION_HEIGHT)
  );
  const gridSlots = columns * rows;
  const measureGridHeight = useCallback(() => {
    if (!active || !gridRegionRef.current) return;

    const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
    const { top } = gridRegionRef.current.getBoundingClientRect();
    setAvailableGridHeight(
      Math.max(0, Math.floor(viewportHeight - top - pageBottomPadding - 8))
    );
  }, [active, pageBottomPadding]);

  useEffect(() => {
    if (!active) return;

    const frame = window.requestAnimationFrame(measureGridHeight);
    const observer = new ResizeObserver(measureGridHeight);
    const visualViewport = window.visualViewport;
    if (gridRegionRef.current) observer.observe(gridRegionRef.current);
    window.addEventListener("resize", measureGridHeight);
    visualViewport?.addEventListener("resize", measureGridHeight);

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", measureGridHeight);
      visualViewport?.removeEventListener("resize", measureGridHeight);
    };
  }, [active, measureGridHeight]);
  const [ownership, setOwnership] = useState<MineOwnershipFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [tagPredicates, setTagPredicates] = useState<TagResourcePredicate[]>(
    []
  );
  const [page, setPage] = useState(1);
  const { data: tagLibraries } = useTagLibraries();
  const defaultTagLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: tagDefinitions } = useTagDefinitions(
    defaultTagLibrary?.bucket_id ?? null
  );
  const searchTagPredicates = useMemo(
    () => getTagSearchPredicates(tagDefinitions, searchQuery, t),
    [tagDefinitions, searchQuery, t]
  );
  const createCardInGrid = gridSlots > 1;
  const pageSize = Math.max(1, gridSlots - (createCardInGrid ? 1 : 0));
  const listParams = useMemo(
    (): AgentListFilters => ({
      tenantId: user?.tenantId ?? null,
      enabled: active,
      page,
      pageSize,
      search: searchQuery.trim() || undefined,
      tagPredicates,
      searchTagPredicates,
      createdBy: ownership === "created" ? user?.id : undefined,
      createdByNot: ownership === "others" ? user?.id : undefined,
    }),
    [
      active,
      user?.tenantId,
      user?.id,
      ownership,
      page,
      pageSize,
      searchQuery,
      tagPredicates,
      searchTagPredicates,
    ]
  );
  const {
    agents: listedAgents,
    creatorCounts,
    pagination,
    isLoading,
    isError,
    isFetching,
    refetch,
  } = useAgentList(listParams);
  const agents: MyEditableAgentItem[] = useMemo(
    () => listedAgents.map(toMyAgentItem),
    [listedAgents]
  );
  const counts = creatorCounts ?? { all: 0, created: 0, others: 0 };
  const total = pagination?.total ?? 0;
  useEffect(() => {
    if (active && creatorCounts && tagPredicates.length === 0) {
      onTotalChange?.(creatorCounts.all);
    }
  }, [active, creatorCounts, onTotalChange, tagPredicates.length]);
  const gridHeight =
    availableGridHeight === null
      ? undefined
      : Math.max(0, availableGridHeight - (total > 0 ? PAGINATION_HEIGHT : 0));
  const reviewDeepLink = useMemo(
    () => parseReviewDeepLinkParams(searchParams),
    [searchParams]
  );
  const { data: deepLinkMineData, isLoading: deepLinkFallbackLoading } =
    useMyEditableAgents(
      {
        ownership: "all",
        agent_id: reviewDeepLink?.agentId,
        page: 1,
        page_size: 1,
        new_agent_padding: false,
      },
      active && reviewDeepLink != null
    );
  const deepLinkFallbackAgent = useMemo(() => {
    const item = deepLinkMineData?.items?.[0];
    return item && !isNewAgentPaddingItem(item) ? item : null;
  }, [deepLinkMineData]);
  const onReviewDeepLinkConsumed = useCallback(() => {
    router.replace(`/${locale}/agent-space?tab=mine`);
  }, [locale, router]);
  const onOwnershipChange = (value: MineOwnershipFilter) => {
    setOwnership(value);
    setPage(1);
  };
  const onSearchChange = (value: string) => {
    setSearchQuery(value);
    setPage(1);
  };
  const onTagPredicatesChange = (value: TagResourcePredicate[]) => {
    setTagPredicates(value);
    setPage(1);
  };
  const [createAgentModalVisible, setCreateAgentModalVisible] = useState(false);
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewModalAgent, setReviewModalAgent] =
    useState<MyEditableAgentItem | null>(null);
  const [reviewModalInfo, setReviewModalInfo] =
    useState<MyAgentRepositoryInfoItem | null>(null);
  const [reviewModalMode, setReviewModalMode] = useState<
    "review" | "reviewUpdate"
  >("review");
  const [applyingAgentId, setApplyingAgentId] = useState<number | null>(null);
  const [detailTarget, setDetailTarget] = useState<{
    agentId: number;
    versionNo: number;
    agent: MyEditableAgentItem;
  } | null>(null);
  const {
    data: versionDetail,
    isLoading: isDetailLoading,
    isError: isDetailError,
    isFetching: isDetailFetching,
    refetch: refetchDetail,
  } = useAgentVersionDetail(
    detailTarget?.agentId ?? null,
    detailTarget?.versionNo ?? null,
    active && detailTarget != null
  );
  const { tools: availableTools } = useToolList({
    enabled: active && detailTarget != null,
  });
  const { skills: availableSkills } = useSkillList({
    enabled: active && detailTarget != null,
  });
  const {
    data: detailListings,
    isLoading: isDetailListingsLoading,
    isError: isDetailListingsError,
    isFetching: isDetailListingsFetching,
    refetch: refetchDetailListings,
  } = useAgentRepositoryListings(
    detailTarget
      ? { agent_id: detailTarget.agentId, page: 1, page_size: 100 }
      : undefined,
    active && detailTarget != null
  );
  const detail = useMemo(() => {
    if (!detailTarget) return null;
    if (!versionDetail) return undefined;
    const repositoryInfo = pickReviewDisplayRepositoryInfo(
      toMineRepositoryInfo(detailListings?.items ?? [])
    );
    return {
      ...mapMyAgentDetail(versionDetail, detailTarget.agent, {
        tools: availableTools,
        skills: availableSkills,
      }),
      status: repositoryInfo?.status,
    };
  }, [
    availableSkills,
    availableTools,
    detailTarget,
    detailListings,
    versionDetail,
  ]);
  const [applyModalOpen, setApplyModalOpen] = useState(false);
  const [applyModalAgent, setApplyModalAgent] =
    useState<MyEditableAgentItem | null>(null);
  const consumedDeepLinkRef = useRef<number | null>(null);

  const createListingMutation = useCreateAgentRepositoryListing();
  const updateStatusMutation = useUpdateAgentRepositoryStatus();
  const deleteAgentMutation = useMutation({
    mutationFn: (agentId: number) => deleteAgent(agentId),
  });

  const normalizedQuery = searchQuery.trim().toLowerCase();

  const handleCreateAgent = () => {
    setCreateAgentModalVisible(true);
  };

  const handleAgentCreated = async ({ agentId }: CreatedAgentResult) => {
    setCreateAgentModalVisible(false);
    await Promise.all([
      invalidateAgentRepositoryCaches(queryClient),
      queryClient.invalidateQueries({ queryKey: [AGENTS_LIST_QUERY_KEY] }),
    ]);
    router.push(`/${locale}/agents?agent_id=${agentId}`);
  };

  const handleEdit = (
    agentId: number,
    permission?: MyEditableAgentItem["permission"]
  ) => {
    if (permission === "READ_ONLY") {
      return;
    }
    router.push(
      `/${locale}/agents?agent_id=${agentId}&from=agent-space&tab=mine`
    );
  };

  const handleDeleteAgent = (agent: MyEditableAgentItem) => {
    const name = agent.name?.trim() || t("agentRepository.card.untitled");
    confirm({
      title: t("businessLogic.config.modal.deleteTitle"),
      content: t("businessLogic.config.modal.deleteContent", { name }),
      onOk: async () => {
        try {
          const result = await deleteAgentMutation.mutateAsync(agent.agent_id);
          if (!result.success) {
            throw new Error(result.message || "delete failed");
          }
          message.success(
            t("businessLogic.config.error.agentDeleteSuccess", { name })
          );
          await Promise.all([
            invalidateAgentRepositoryCaches(queryClient),
            queryClient.invalidateQueries({
              queryKey: [AGENTS_LIST_QUERY_KEY],
            }),
          ]);
        } catch (error) {
          log.error("Failed to delete agent:", error);
          message.error(t("businessLogic.config.error.agentDeleteFailed"));
          throw error;
        }
      },
    });
  };

  const handleEvaluate = (agent: MyEditableAgentItem) => {
    const versionNo = agent.current_version_no ?? 0;
    if (versionNo <= 0) {
      return;
    }
    router.push(
      `/${locale}/evaluation?agent_ids=${encodeURIComponent(JSON.stringify([agent.agent_id]))}`
    );
  };

  const closeReviewModal = () => {
    setReviewModalOpen(false);
    setReviewModalAgent(null);
    setReviewModalInfo(null);
  };

  const handleApplyListing = (agent: MyEditableAgentItem) => {
    const versionNo = agent.current_version_no ?? 0;
    if (versionNo <= 0) {
      return;
    }
    setApplyModalAgent(agent);
    setApplyModalOpen(true);
  };

  const closeApplyModal = () => {
    setApplyModalOpen(false);
    setApplyModalAgent(null);
  };

  const handleSubmitApplyListing = async (
    payload: AgentRepositoryListingCreatePayload
  ) => {
    if (!applyModalAgent) {
      return;
    }

    const versionNo = applyModalAgent.current_version_no ?? 0;
    if (versionNo <= 0) {
      return;
    }

    setApplyingAgentId(applyModalAgent.agent_id);
    try {
      await createListingMutation.mutateAsync({
        agentId: applyModalAgent.agent_id,
        versionNo,
        payload,
      });
      message.success(t("repository.mine.applySuccess"));
      closeApplyModal();
    } catch {
      message.error(t("repository.mine.applyError"));
    } finally {
      setApplyingAgentId(null);
    }
  };

  const handleViewReview = (
    agent: MyEditableAgentItem,
    mode: "review" | "reviewUpdate"
  ) => {
    const repositoryInfo = pickReviewDisplayRepositoryInfo(
      agent.repository_info ?? []
    );
    if (!repositoryInfo) {
      return;
    }
    openReviewModal(agent, repositoryInfo, mode);
  };

  const openReviewModal = (
    agent: MyEditableAgentItem,
    repositoryInfo: MyAgentRepositoryInfoItem,
    mode: "review" | "reviewUpdate"
  ) => {
    setReviewModalAgent(agent);
    setReviewModalInfo(repositoryInfo);
    setReviewModalMode(mode);
    setReviewModalOpen(true);
  };

  useEffect(() => {
    if (!active) return;
    if (!reviewDeepLink) {
      consumedDeepLinkRef.current = null;
      return;
    }

    if (consumedDeepLinkRef.current === reviewDeepLink.agentRepositoryId) {
      return;
    }

    const listStillLoading = isLoading;
    const fallbackStillLoading = deepLinkFallbackLoading;
    if (listStillLoading && fallbackStillLoading) {
      return;
    }

    const agentFromList = agents.find(
      (item) => item.agent_id === reviewDeepLink.agentId
    );
    const agent = deepLinkFallbackAgent ?? agentFromList;

    if (!agent) {
      if (listStillLoading || fallbackStillLoading) {
        return;
      }
      message.error(t("notifications.deepLink.agentNotFound"));
      consumedDeepLinkRef.current = reviewDeepLink.agentRepositoryId;
      onReviewDeepLinkConsumed?.();
      return;
    }

    const repositoryInfo = findRepositoryInfoById(
      agent.repository_info ?? [],
      reviewDeepLink.agentRepositoryId
    );

    if (!repositoryInfo) {
      message.error(t("notifications.deepLink.agentNotFound"));
      consumedDeepLinkRef.current = reviewDeepLink.agentRepositoryId;
      onReviewDeepLinkConsumed?.();
      return;
    }

    openReviewModal(
      agent,
      repositoryInfo,
      resolveReviewModalMode(agent, repositoryInfo)
    );
    consumedDeepLinkRef.current = reviewDeepLink.agentRepositoryId;
    onReviewDeepLinkConsumed?.();
  }, [
    active,
    agents,
    deepLinkFallbackAgent,
    deepLinkFallbackLoading,
    isLoading,
    message,
    onReviewDeepLinkConsumed,
    reviewDeepLink,
    t,
  ]);

  const handleSetNotShared = async () => {
    if (!reviewModalInfo) {
      return;
    }

    const canUpdate =
      isCancelableRepositoryStatus(reviewModalInfo.status) ||
      isTakeDownableRepositoryStatus(reviewModalInfo.status);
    if (!canUpdate) {
      return;
    }

    const wasShared = reviewModalInfo.status === "shared";

    try {
      await updateStatusMutation.mutateAsync({
        agentRepositoryId: reviewModalInfo.agent_repository_id,
        status: "not_shared",
      });
      message.success(
        wasShared
          ? t("repository.mine.takeDownSuccess")
          : t("repository.mine.cancelApplySuccess")
      );
      closeReviewModal();
    } catch {
      message.error(
        wasShared
          ? t("repository.mine.takeDownError")
          : t("repository.mine.cancelApplyError")
      );
      throw new Error("Update repository status failed");
    }
  };

  const ownershipLabelKey: Record<MineOwnershipFilter, string> = {
    all: "repository.mine.filter.all",
    created: "repository.mine.filter.created",
    others: "repository.mine.filter.others",
  };

  const hasActiveFilter =
    ownership !== "all" ||
    normalizedQuery.length > 0 ||
    tagPredicates.length > 0;
  const showFilteredEmpty =
    !isLoading && !isError && agents.length === 0 && hasActiveFilter;
  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t("agentRepository.mine.searchPlaceholder")}
            prefix={<Search className="size-4 text-slate-400" aria-hidden />}
            className="rounded-xl"
            allowClear
          />
        </div>
        <TagFilterPopover
          definitions={tagDefinitions ?? []}
          value={tagPredicates}
          onChange={onTagPredicatesChange}
        />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {MINE_OWNERSHIP_FILTERS.map((filter) => (
          <button
            key={filter}
            type="button"
            onClick={() => onOwnershipChange(filter)}
            className={`flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
              ownership === filter
                ? "bg-primary text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            }`}
          >
            {t(ownershipLabelKey[filter])}
            <span
              className={`rounded px-1.5 text-xs ${
                ownership === filter
                  ? "bg-white/20"
                  : "bg-white/70 text-slate-500 dark:bg-slate-900/50 dark:text-slate-400"
              }`}
            >
              {counts[filter]}
            </span>
          </button>
        ))}
      </div>

      <div ref={gridRegionRef} className="min-h-0">
        {!createCardInGrid ? (
          <div className="mb-5">
            <CreateNewAgentCard onClick={handleCreateAgent} />
          </div>
        ) : null}
        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Spin size="large" />
          </div>
        ) : isError ? (
          <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-200 py-16 text-center dark:border-slate-700">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {t("agentRepository.mine.loadError")}
            </p>
            <Button
              type="primary"
              onClick={() => refetch()}
              loading={isFetching}
            >
              {t("repository.common.retry")}
            </Button>
          </div>
        ) : (
          <>
            <ResourceCardGrid
              items={agents}
              columns={columns}
              rows={rows}
              gridHeight={showFilteredEmpty ? undefined : gridHeight}
              page={page}
              total={total}
              onPageChange={setPage}
              paginateItems={false}
              showToolbar={false}
              emptyState={
                showFilteredEmpty ? (
                  <Empty
                    description={t("agentRepository.mine.emptyFiltered")}
                  />
                ) : undefined
              }
              showCreateCard={createCardInGrid}
              createCard={
                createCardInGrid ? (
                  <CreateNewAgentCard onClick={handleCreateAgent} />
                ) : undefined
              }
              renderItem={(agent) => (
                <MyAgentCard
                  key={agent.agent_id}
                  agent={agent}
                  onEdit={() => handleEdit(agent.agent_id, agent.permission)}
                  onView={() =>
                    setDetailTarget({
                      agentId: agent.agent_id,
                      versionNo: agent.current_version_no ?? 0,
                      agent,
                    })
                  }
                  onApplyListing={() => handleApplyListing(agent)}
                  onViewReview={handleViewReview}
                  onDelete={() => handleDeleteAgent(agent)}
                  onEvaluate={() => handleEvaluate(agent)}
                  isApplying={
                    applyingAgentId === agent.agent_id &&
                    createListingMutation.isPending
                  }
                  isDeleting={
                    deleteAgentMutation.isPending &&
                    deleteAgentMutation.variables === agent.agent_id
                  }
                />
              )}
            />
            {showFilteredEmpty && createCardInGrid ? (
              <Empty
                className="py-16"
                description={t("agentRepository.mine.emptyFiltered")}
              />
            ) : null}
          </>
        )}
      </div>

      <MineApplyListingModal
        open={active && applyModalOpen}
        agent={applyModalAgent}
        isSubmitting={createListingMutation.isPending}
        onClose={closeApplyModal}
        onSubmit={handleSubmitApplyListing}
      />

      <MineReviewStatusModal
        open={active && reviewModalOpen}
        agent={reviewModalAgent}
        repositoryInfo={reviewModalInfo}
        mode={reviewModalMode}
        isUpdatingStatus={updateStatusMutation.isPending}
        onClose={closeReviewModal}
        onSetNotShared={handleSetNotShared}
      />

      <CreateAgentModal
        open={active && createAgentModalVisible}
        onCancel={() => setCreateAgentModalVisible(false)}
        onCreated={handleAgentCreated}
      />
      <AgentDetail
        open={active && detailTarget != null}
        onClose={() => setDetailTarget(null)}
        onEdit={
          detailTarget?.agent.permission === "READ_ONLY"
            ? undefined
            : detailTarget
              ? () =>
                  handleEdit(
                    detailTarget.agentId,
                    detailTarget.agent.permission
                  )
              : undefined
        }
        detail={detail}
        agentIcon={
          detailTarget ? (
            <MyAgentIcon agent={detailTarget.agent} size={48} iconSize={24} />
          ) : undefined
        }
        published={(detailTarget?.versionNo ?? 0) > 0}
        status={detail?.status}
        isLoading={isDetailLoading || isDetailListingsLoading}
        isError={isDetailError || isDetailListingsError}
        isFetching={isDetailFetching || isDetailListingsFetching}
        onRetry={() => {
          void refetchDetail();
          void refetchDetailListings();
        }}
      />
    </div>
  );
}

function toMyAgentItem(agent: Agent): MyEditableAgentItem {
  const currentVersionNo = agent.current_version_no ?? 0;
  return {
    agent_id: Number(agent.id),
    icon_url: agent.icon_url,
    name: agent.display_name || agent.name,
    description: agent.description,
    current_version_no: currentVersionNo,
    version_label:
      agent.version_label ??
      (currentVersionNo > 0 ? `V${currentVersionNo}` : null),
    version_create_time: agent.version_create_time ?? null,
    permission: agent.permission,
    tags: agent.tags,
    repository_info: [],
  };
}

function getRowCount(availableHeight: number) {
  if (availableHeight <= 0) return 3;
  return Math.min(
    3,
    Math.max(
      1,
      Math.floor((availableHeight + CARD_GAP) / (MIN_CARD_HEIGHT + CARD_GAP))
    )
  );
}
