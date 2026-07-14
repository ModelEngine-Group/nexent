"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Button, Empty, Input, Spin } from "antd";
import { ChevronLeft, ChevronRight, Plus, Search, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import AgentImportWizard from "@/components/agent/AgentImportWizard";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { deleteAgent } from "@/services/agentConfigService";
import {
  AGENTS_LIST_QUERY_KEY,
  invalidateAgentRepositoryCaches,
  useCreateAgentRepositoryListing,
  useUpdateAgentRepositoryStatus,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import {
  parseAgentImportFile,
  selectFile,
  type ImportAgentData,
} from "@/lib/agentImportUtils";
import log from "@/lib/logger";
import {
  isCancelableRepositoryStatus,
  isTakeDownableRepositoryStatus,
  pickReviewDisplayRepositoryInfo,
} from "@/lib/agentRepositoryMine";
import {
  isNewAgentPaddingItem,
  type AgentRepositoryListingCreatePayload,
  type MineOwnershipFilter,
  type MyAgentRepositoryInfoItem,
  type MyEditableAgentItem,
  type MyEditableAgentListItem,
  type MyEditableAgentOwnershipCounts,
} from "@/types/agentRepository";
import { MineApplyListingModal } from "./MineApplyListingModal";
import { MineReviewStatusModal } from "./MineReviewStatusModal";
import { CreateNewAgentCard } from "./CreateNewAgentCard";
import { MyAgentCard } from "./MyAgentCard";

const MINE_OWNERSHIP_FILTERS: MineOwnershipFilter[] = [
  "all",
  "created",
  "others",
];

interface MineAgentsViewProps {
  agents: MyEditableAgentListItem[];
  counts: MyEditableAgentOwnershipCounts;
  ownership: MineOwnershipFilter;
  onOwnershipChange: (ownership: MineOwnershipFilter) => void;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onRetry: () => void;
  onViewDetail: (agentId: number, versionNo: number) => void;
}

export function MineAgentsView({
  agents,
  counts,
  ownership,
  onOwnershipChange,
  searchQuery,
  onSearchChange,
  page,
  pageSize,
  total,
  onPageChange,
  isLoading,
  isError,
  isFetching,
  onRetry,
  onViewDetail,
}: MineAgentsViewProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();
  const router = useRouter();
  const queryClient = useQueryClient();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const [importWizardVisible, setImportWizardVisible] = useState(false);
  const [importWizardData, setImportWizardData] =
    useState<ImportAgentData | null>(null);
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
  const deleteAgentMutation = useMutation({
    mutationFn: (agentId: number) => deleteAgent(agentId),
  });

  const normalizedQuery = searchQuery.trim().toLowerCase();

  const handleCreateAgent = () => {
    router.push(`/${locale}/agents?create=true&from=agent-space&tab=mine`);
  };

  const handleImportAgent = async () => {
    const file = await selectFile(".json");
    if (!file) return;

    const agentData = await parseAgentImportFile(file, {
      onParseError: (msgKey) => message.error(t(msgKey)),
      onValidationError: (msgKey) => message.error(t(msgKey)),
      onGenericError: (error) => {
        log.error("Failed to read import file:", error);
        message.error(t("businessLogic.config.error.agentImportFailed"));
      },
    });

    if (!agentData) return;

    setImportWizardData(agentData);
    setImportWizardVisible(true);
  };

  const handleEdit = (agentId: number, permission?: MyEditableAgentItem["permission"]) => {
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
    router.push(`/${locale}/space/agents/${agent.agent_id}/evaluate?back_tab=mine`);
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
  const showFilteredEmpty = !isLoading && !isError && agents.length === 0;
  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 0;
  const showPagination = !isLoading && !isError && totalPages > 1;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-md">
          <Input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t("agentRepository.mine.searchPlaceholder")}
            prefix={<Search className="size-4 text-slate-400" aria-hidden />}
            className="h-11 rounded-xl"
            allowClear
          />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            className="flex h-11 items-center gap-1.5"
            onClick={handleImportAgent}
          >
            <Upload className="size-4" aria-hidden />
            {t("agentConfig.button.import")}
          </Button>
          <Button
            type="primary"
            className="flex h-11 items-center gap-1.5"
            onClick={handleCreateAgent}
          >
            <Plus className="size-4" aria-hidden />
            {t("agentRepository.mine.newAgentButton")}
          </Button>
        </div>
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
        <>
          <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) =>
              isNewAgentPaddingItem(agent) ? (
                <div key="new-agent-padding" className="h-full">
                  <CreateNewAgentCard onClick={handleCreateAgent} />
                </div>
              ) : (
                <div key={agent.agent_id} className="h-full">
                  <MyAgentCard
                    agent={agent}
                    onEdit={() => handleEdit(agent.agent_id, agent.permission)}
                    onView={() =>
                      onViewDetail(
                        agent.agent_id,
                        agent.current_version_no ?? 0
                      )
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
                </div>
              )
            )}
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

      <AgentImportWizard
        visible={importWizardVisible}
        onCancel={() => {
          setImportWizardVisible(false);
          setImportWizardData(null);
        }}
        initialData={importWizardData}
        onImportComplete={async () => {
          setImportWizardVisible(false);
          setImportWizardData(null);
          await Promise.all([
            invalidateAgentRepositoryCaches(queryClient),
            queryClient.invalidateQueries({ queryKey: [AGENTS_LIST_QUERY_KEY] }),
          ]);
        }}
      />
    </div>
  );
}
