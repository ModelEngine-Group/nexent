"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { App, Button, Empty, Input, Spin } from "antd";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  useCreateAgentRepositoryListing,
  useUpdateAgentRepositoryStatus,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import {
  isCancelableRepositoryStatus,
  isTakeDownableRepositoryStatus,
  pickReviewDisplayRepositoryInfo,
} from "@/lib/agentRepositoryMine";
import type {
  AgentRepositoryListingCreatePayload,
  MineOwnershipFilter,
  MyAgentRepositoryInfoItem,
  MyEditableAgentItem,
  MyEditableAgentOwnershipCounts,
} from "@/types/agentRepository";
import { MineApplyListingModal } from "./MineApplyListingModal";
import { MineReviewStatusModal } from "./MineReviewStatusModal";
import { MyAgentCard } from "./MyAgentCard";

const MINE_OWNERSHIP_FILTERS: MineOwnershipFilter[] = [
  "all",
  "created",
  "others",
];

interface MineAgentsViewProps {
  agents: MyEditableAgentItem[];
  counts: MyEditableAgentOwnershipCounts;
  ownership: MineOwnershipFilter;
  onOwnershipChange: (ownership: MineOwnershipFilter) => void;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onRetry: () => void;
}

export function MineAgentsView({
  agents,
  counts,
  ownership,
  onOwnershipChange,
  isLoading,
  isError,
  isFetching,
  onRetry,
}: MineAgentsViewProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const [searchQuery, setSearchQuery] = useState("");
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewModalAgent, setReviewModalAgent] =
    useState<MyEditableAgentItem | null>(null);
  const [reviewModalInfo, setReviewModalInfo] =
    useState<MyAgentRepositoryInfoItem | null>(null);
  const [reviewModalMode, setReviewModalMode] = useState<
    "review" | "reviewUpdate"
  >("review");
  const [applyingAgentId, setApplyingAgentId] = useState<number | null>(null);
  const [applyModalOpen, setApplyModalOpen] = useState(false);
  const [applyModalAgent, setApplyModalAgent] =
    useState<MyEditableAgentItem | null>(null);

  const createListingMutation = useCreateAgentRepositoryListing();
  const updateStatusMutation = useUpdateAgentRepositoryStatus();

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filteredAgents = useMemo(() => {
    if (!normalizedQuery) {
      return agents;
    }
    return agents.filter((agent) => {
      const name = (agent.name || "").toLowerCase();
      const description = (agent.description || "").toLowerCase();
      return name.includes(normalizedQuery) || description.includes(normalizedQuery);
    });
  }, [agents, normalizedQuery]);

  const handleEdit = (agentId: number) => {
    router.push(`/${locale}/agents?agent_id=${agentId}`);
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
      message.success(
        t("agentRepository.mine.applySuccess", {
          name:
            applyModalAgent.name?.trim() ||
            t("agentRepository.card.untitled"),
        })
      );
      closeApplyModal();
    } catch {
      message.error(t("agentRepository.mine.applyError"));
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
    setReviewModalAgent(agent);
    setReviewModalInfo(repositoryInfo);
    setReviewModalMode(mode);
    setReviewModalOpen(true);
  };

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
          ? t("agentRepository.mine.takeDownSuccess")
          : t("agentRepository.mine.cancelApplySuccess")
      );
      closeReviewModal();
    } catch {
      message.error(
        wasShared
          ? t("agentRepository.mine.takeDownError")
          : t("agentRepository.mine.cancelApplyError")
      );
      throw new Error("Update repository status failed");
    }
  };

  const ownershipLabelKey: Record<MineOwnershipFilter, string> = {
    all: "agentRepository.mine.filter.all",
    created: "agentRepository.mine.filter.created",
    others: "agentRepository.mine.filter.others",
  };

  const hasActiveFilter = ownership !== "all" || normalizedQuery.length > 0;
  const showFilteredEmpty = !isLoading && !isError && filteredAgents.length === 0;

  return (
    <div className="space-y-5">
      <div className="relative">
        <Search className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t("agentRepository.mine.searchPlaceholder")}
          className="h-11 rounded-xl pl-10"
          allowClear
        />
      </div>

      <div className="flex flex-wrap gap-1.5">
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
          <Button type="primary" onClick={onRetry} loading={isFetching}>
            {t("agentRepository.page.retry")}
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
        <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredAgents.map((agent) => (
            <div key={agent.agent_id} className="h-full">
              <MyAgentCard
                agent={agent}
                onEdit={() => handleEdit(agent.agent_id)}
                onApplyListing={() => handleApplyListing(agent)}
                onViewReview={(mode) => handleViewReview(agent, mode)}
                isApplying={
                  applyingAgentId === agent.agent_id &&
                  createListingMutation.isPending
                }
              />
            </div>
          ))}
        </div>
      )}

      <MineApplyListingModal
        open={applyModalOpen}
        agent={applyModalAgent}
        isSubmitting={createListingMutation.isPending}
        onClose={closeApplyModal}
        onSubmit={handleSubmitApplyListing}
      />

      <MineReviewStatusModal
        open={reviewModalOpen}
        agent={reviewModalAgent}
        repositoryInfo={reviewModalInfo}
        mode={reviewModalMode}
        isUpdatingStatus={updateStatusMutation.isPending}
        onClose={closeReviewModal}
        onSetNotShared={handleSetNotShared}
      />
    </div>
  );
}
