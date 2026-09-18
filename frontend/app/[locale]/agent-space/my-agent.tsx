"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Button, Empty, Input, Spin } from "antd";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import CreateAgentModal, {
  type CreatedAgentResult,
} from "@/components/agent/CreateAgentModal";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { deleteAgent } from "@/services/agentConfigService";
import {
  AGENTS_LIST_QUERY_KEY,
  invalidateAgentRepositoryCaches,
  useCreateAgentRepositoryListing,
  useMyEditableAgents,
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
import { mapAgentVersionDetail } from "@/lib/agentRepositoryDetail";
import { AgentRepositoryDetailModal } from "./components/AgentRepositoryDetailModal";

const MINE_OWNERSHIP_FILTERS: MineOwnershipFilter[] = [
  "all",
  "created",
  "others",
];
const MINE_PAGE_SIZE = 12;

export function MyAgent({ active }: { active: boolean }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const [ownership, setOwnership] = useState<MineOwnershipFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [tagPredicates, setTagPredicates] = useState<TagResourcePredicate[]>(
    []
  );
  const [page, setPage] = useState(1);
  const pageSize = MINE_PAGE_SIZE;
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
  const listParams = useMemo(
    () => ({
      ownership,
      page,
      page_size: pageSize,
      ...(searchQuery.trim() ? { search: searchQuery.trim() } : {}),
      ...(tagPredicates.length > 0 ? { tag_predicates: tagPredicates } : {}),
      ...(searchTagPredicates.length > 0
        ? { search_tag_predicates: searchTagPredicates }
        : {}),
      ...(ownership === "all" &&
      !searchQuery.trim() &&
      tagPredicates.length === 0
        ? { new_agent_padding: true }
        : {}),
    }),
    [ownership, page, pageSize, searchQuery, tagPredicates, searchTagPredicates]
  );
  const { data, isLoading, isError, isFetching, refetch } = useMyEditableAgents(
    listParams,
    active
  );
  const agents = useMemo(() => data?.items ?? [], [data?.items]);
  const counts = data?.counts ?? { all: 0, created: 0, others: 0 };
  const total = data?.pagination?.total ?? 0;
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
  const detail = useMemo(
    () =>
      versionDetail
        ? mapAgentVersionDetail(versionDetail)
        : detailTarget
          ? undefined
          : null,
    [detailTarget, versionDetail]
  );
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
    router.push(`/${locale}/evaluation?agent_id=${agent.agent_id}`);
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
      (item): item is MyEditableAgentItem =>
        !isNewAgentPaddingItem(item) && item.agent_id === reviewDeepLink.agentId
    );
    const agent = agentFromList ?? deepLinkFallbackAgent;

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
  const showFilteredEmpty = !isLoading && !isError && agents.length === 0;
  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t("agentRepository.mine.searchPlaceholder")}
            prefix={<Search className="size-4 text-slate-400" aria-hidden />}
            className="h-10 rounded-xl"
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

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-200 py-16 text-center dark:border-slate-700">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("agentRepository.mine.loadError")}
          </p>
          <Button type="primary" onClick={() => refetch()} loading={isFetching}>
            {t("repository.common.retry")}
          </Button>
        </div>
      ) : showFilteredEmpty ? (
        <Empty
          className="py-16"
          description={
            hasActiveFilter
              ? t("agentRepository.mine.emptyFiltered")
              : t("agentRepository.mine.empty")
          }
        />
      ) : (
        <>
          <ResourceCardGrid
            items={agents}
            columns={4}
            page={page}
            total={total}
            onPageChange={setPage}
            paginateItems={false}
            showToolbar={false}
            renderItem={(agent) =>
              isNewAgentPaddingItem(agent) ? (
                <CreateNewAgentCard
                  key="new-agent-padding"
                  onClick={handleCreateAgent}
                />
              ) : (
                <MyAgentCard
                  key={agent.agent_id}
                  agent={agent}
                  onEdit={() => handleEdit(agent.agent_id, agent.permission)}
                  onView={() =>
                    setDetailTarget({
                      agentId: agent.agent_id,
                      versionNo: agent.current_version_no ?? 0,
                    })
                  }
                  onApplyListing={() => handleApplyListing(agent)}
                  onViewReview={(mode) => handleViewReview(agent, mode)}
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
              )
            }
          />
        </>
      )}

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
      <AgentRepositoryDetailModal
        open={active && detailTarget != null}
        onClose={() => setDetailTarget(null)}
        detail={detail}
        isLoading={isDetailLoading}
        isError={isDetailError}
        isFetching={isDetailFetching}
        onRetry={() => refetchDetail()}
      />
    </div>
  );
}
