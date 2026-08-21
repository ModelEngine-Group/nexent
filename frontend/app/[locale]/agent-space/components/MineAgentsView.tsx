"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Button, Empty, Input, Modal, Spin, Tag } from "antd";
import { ChevronLeft, ChevronRight, Download, Plus, Search, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import AgentImportWizard from "@/components/agent/AgentImportWizard";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import {
  deleteAgent,
  exportAgentsBatch,
  importAgentsBatch,
  type AgentBatchImportResult,
} from "@/services/agentConfigService";
import {
  AGENTS_LIST_QUERY_KEY,
  invalidateAgentRepositoryCaches,
  useCreateAgentRepositoryListing,
  useUpdateAgentRepositoryStatus,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import {
  parseAgentImportFile,
  selectImportFile,
  type ImportAgentData,
} from "@/lib/agentImportUtils";
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

export interface ReviewDeepLinkTarget {
  agentRepositoryId: number;
  agentId: number;
}

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
  reviewDeepLink?: ReviewDeepLinkTarget | null;
  deepLinkFallbackAgent?: MyEditableAgentItem | null;
  deepLinkFallbackLoading?: boolean;
  onReviewDeepLinkConsumed?: () => void;
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
  reviewDeepLink = null,
  deepLinkFallbackAgent = null,
  deepLinkFallbackLoading = false,
  onReviewDeepLinkConsumed,
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
  const consumedDeepLinkRef = useRef<number | null>(null);

  // Batch export / import state
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedAgentIds, setSelectedAgentIds] = useState<Set<number>>(
    new Set()
  );
  const [isBatchExporting, setIsBatchExporting] = useState(false);
  const [isBatchImporting, setIsBatchImporting] = useState(false);
  const [batchImportResult, setBatchImportResult] =
    useState<AgentBatchImportResult | null>(null);
  const [batchImportResultVisible, setBatchImportResultVisible] =
    useState(false);

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
    const selection = await selectImportFile();

    if (selection.type === "cancelled") {
      return;
    }

    if (selection.type === "batch") {
      setIsBatchImporting(true);
      try {
        const result = await importAgentsBatch(selection.file);
        if (result.success && result.data) {
          const data = result.data;
          if (data.failed_count > 0) {
            setBatchImportResult(data);
            setBatchImportResultVisible(true);
          } else {
            message.success(
              t("agentRepository.mine.batchImport.success", {
                success: data.success_count,
                failed: data.failed_count,
              })
            );
          }
          await Promise.all([
            invalidateAgentRepositoryCaches(queryClient),
            queryClient.invalidateQueries({
              queryKey: [AGENTS_LIST_QUERY_KEY],
            }),
          ]);
        } else {
          message.error(result.message || t("agentRepository.mine.batchImport.failed"));
        }
      } finally {
        setIsBatchImporting(false);
      }
      return;
    }

    // Single agent path: parse the file and open the wizard.
    const data = await parseAgentImportFile(selection.file, {
      onParseError: (msgKey) => {
        message.error(t(msgKey) || msgKey);
      },
      onValidationError: (msgKey) => {
        message.error(t(msgKey) || msgKey);
      },
      onGenericError: (error) => {
        log.error("Failed to read import file:", error);
        message.error(t("businessLogic.config.error.agentImportFailed") || "Failed to import agent");
      },
    });

    if (data) {
      setImportWizardData(data);
      setImportWizardVisible(true);
    }
  };

  const handleToggleSelect = (agentId: number) => {
    setSelectedAgentIds((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) {
        next.delete(agentId);
      } else {
        next.add(agentId);
      }
      return next;
    });
  };

  const handleEnterSelectMode = () => {
    setSelectionMode(true);
    setSelectedAgentIds(new Set());
  };

  const handleExitSelectMode = () => {
    setSelectionMode(false);
    setSelectedAgentIds(new Set());
  };

  const handleBatchExport = async () => {
    if (selectedAgentIds.size === 0) {
      message.warning(t("agentRepository.mine.batchExport.empty"));
      return;
    }
    setIsBatchExporting(true);
    try {
      const result = await exportAgentsBatch(Array.from(selectedAgentIds));
      if (result.success) {
        message.success(t("agentRepository.mine.batchExport.success"));
        handleExitSelectMode();
      } else {
        message.error(result.message || t("agentRepository.mine.batchExport.failed"));
      }
    } finally {
      setIsBatchExporting(false);
    }
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
            queryClient.invalidateQueries({ queryKey: [AGENTS_LIST_QUERY_KEY] }),
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
      message.success(
        t("repository.mine.applySuccess")
      );
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
    agents,
    deepLinkFallbackAgent,
    deepLinkFallbackLoading,
    isLoading,
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
          {selectionMode ? (
            <>
              <span className="text-sm text-slate-500 dark:text-slate-400">
                {t("agentRepository.mine.batchExport.selected", {
                  count: selectedAgentIds.size,
                })}
              </span>
              <Button
                className="flex h-11 items-center gap-1.5"
                onClick={handleExitSelectMode}
              >
                {t("agentRepository.mine.batchExport.cancelSelect")}
              </Button>
              <Button
                type="primary"
                className="flex h-11 items-center gap-1.5"
                onClick={handleBatchExport}
                loading={isBatchExporting}
                disabled={selectedAgentIds.size === 0}
              >
                <Download className="size-4" aria-hidden />
                {t("agentRepository.mine.exportButton")}
              </Button>
            </>
          ) : (
            <>
              <Button
                className="flex h-11 items-center gap-1.5"
                onClick={handleEnterSelectMode}
              >
                <Download className="size-4" aria-hidden />
                {t("agentRepository.mine.exportButton")}
              </Button>
              <Button
                className="flex h-11 items-center gap-1.5"
                onClick={handleImportAgent}
                loading={isBatchImporting}
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
            </>
          )}
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
                    selectionMode={selectionMode}
                    isSelected={selectedAgentIds.has(agent.agent_id)}
                    onToggleSelect={() => handleToggleSelect(agent.agent_id)}
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
            queryClient.invalidateQueries({
              queryKey: [AGENTS_LIST_QUERY_KEY],
            }),
          ]);
        }}
      />

      <Modal
        open={batchImportResultVisible}
        title={t("agentRepository.mine.batchImport.resultTitle")}
        onCancel={() => setBatchImportResultVisible(false)}
        onOk={() => setBatchImportResultVisible(false)}
        okText={t("common.ok", "OK")}
        cancelButtonProps={{ style: { display: "none" } }}
      >
        {batchImportResult ? (
          <div className="space-y-3 py-2">
            <div className="flex items-center gap-3">
              <Tag color="green">
                {t("agentRepository.mine.batchImport.successLabel")}:{" "}
                {batchImportResult.success_count}
              </Tag>
              <Tag color="red">
                {t("agentRepository.mine.batchImport.failedLabel")}:{" "}
                {batchImportResult.failed_count}
              </Tag>
            </div>
            {batchImportResult.items.length > 0 ? (
              <div className="max-h-60 space-y-2 overflow-y-auto">
                {batchImportResult.items.map((item, idx) => (
                  <div
                    key={`${item.name}-${idx}`}
                    className={`rounded-md border p-2 text-sm ${
                      item.success
                        ? "border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-900/20"
                        : "border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/20"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">
                        {item.display_name || item.name}
                      </span>
                      <Tag color={item.success ? "success" : "error"}>
                        {item.success
                          ? t("agentRepository.mine.batchImport.successLabel")
                          : t("agentRepository.mine.batchImport.failedLabel")}
                      </Tag>
                    </div>
                    {!item.success && item.error ? (
                      <p className="mt-1 text-xs text-red-600 dark:text-red-400 break-all">
                        {item.error}
                      </p>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
