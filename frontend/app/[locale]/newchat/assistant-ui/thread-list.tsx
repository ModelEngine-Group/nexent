// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Checkbox, message } from "antd";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import {
  AuiIf,
  ThreadListItemPrimitive,
  ThreadListItemMorePrimitive,
  ThreadListPrimitive,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import {
  Clock,
  MoreHorizontalIcon,
  PencilIcon,
  TrashIcon,
  PinIcon,
  PinOffIcon,
  ArrowDownIcon,
  XIcon,
  ChevronRight,
  LayoutGrid,
  Loader2Icon,
  CircleAlertIcon,
  LoaderCircle,
  ListChecks,
} from "lucide-react";
import {
  Fragment,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import log from "@/lib/logger";
import { conversationService } from "@/services/conversationService";
import { getConversationDateBoundaries } from "@/lib/conversationViewport";
import {
  fetchAgentConversationIds,
  getAgentConversationSelectionSummary,
  setAgentConversationSelection,
  toggleAgentConversationSelection,
} from "@/lib/agentConversationSelection";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import {
  resolveThreadAgentId,
  useThreadAgentOverrides,
} from "../adapter/thread-agent-registry";
import type { PublishedAgent } from "@/types/agentConfig";
import type { FC } from "react";
import { setPendingThreadOperationId } from "../adapter/conversation-thread-list-adapter";
import { getVisibleThreadIds } from "./visible-thread-ids";
import { getVisibleAgentThreads } from "./thread-list-visibility";
import { hoistPinnedThreads, usePinnedThreads } from "./thread-pins";
export { PinnedThreadsProvider } from "./thread-pins";

// Conversation status indicator component
const ConversationStatusIndicator: FC<{
  isStreaming: boolean;
  isCompleted: boolean;
}> = ({ isStreaming, isCompleted }) => {
  const { t } = useTranslation();

  if (isStreaming) {
    return (
      <div
        className="flex-shrink-0 w-2 h-2 bg-green-500 rounded-full mr-2 animate-pulse"
        title={t("chat.threadList.running")}
      />
    );
  }

  if (isCompleted) {
    return (
      <div
        className="flex-shrink-0 w-2 h-2 bg-blue-500 rounded-full mr-2"
        title={t("chat.threadList.completed")}
      />
    );
  }

  return null;
};

interface BatchSelectionValue {
  batchMode: boolean;
  selectedIds: Set<string>;
  allVisibleSelected: boolean;
  someVisibleSelected: boolean;
  toggle: (id: string) => void;
  isSelected: (id: string) => boolean;
  selectAllVisible: () => void;
  toggleAgentGroup: (
    agentId: number,
    visibleThreadIds: readonly string[]
  ) => Promise<void>;
  getAgentGroupSelection: (
    agentId: number,
    visibleThreadIds: readonly string[]
  ) => {
    selectedCount: number;
    totalCount: number;
    checked: boolean;
    indeterminate: boolean;
    loading: boolean;
    complete: boolean;
  };
  clear: () => void;
  enter: () => void;
  exit: () => void;
  deleteSelected: () => void;
}

const BatchSelectionContext = createContext<BatchSelectionValue | null>(null);

// Safe hook: returns null outside a provider so list items render normally
// (no batch UI) when the sidebar is not wrapped in BatchSelectionProvider.
const useBatchSelection = (): BatchSelectionValue | null =>
  useContext(BatchSelectionContext);

export const BatchSelectionProvider: FC<{
  children: ReactNode;
  onNewConversation?: () => void | Promise<void>;
  serverConversationIds?: ReadonlyMap<string, string>;
  conversationType?: "agent_chat" | "workbench";
}> = ({
  children,
  onNewConversation,
  serverConversationIds,
  conversationType = "workbench",
}) => {
  const { t } = useTranslation();
  const aui = useAui();
  const { confirm } = useConfirmModal();
  const threadIds = useAuiState((s) => s.threads.threadIds);
  const threadItems = useAuiState((s) => s.threads.threadItems);
  const mainThreadId = useAuiState((s) => s.threads.mainThreadId);
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [agentConversationIds, setAgentConversationIds] = useState<
    ReadonlyMap<number, readonly string[]>
  >(() => new Map());
  const [loadingAgentIds, setLoadingAgentIds] = useState<ReadonlySet<number>>(
    () => new Set()
  );
  const loadingAgentIdsRef = useRef(new Set<number>());
  const itemsById = useMemo(
    () =>
      new Map(
        (threadItems as ReadonlyArray<{ id: string; remoteId?: string }>).map(
          (item) => [item.id, item]
        )
      ),
    [threadItems]
  );
  const resolveRemoteId = useCallback(
    (id: string): string | undefined => {
      const rawId =
        serverConversationIds?.get(id) || itemsById.get(id)?.remoteId;
      const numericId = Number(rawId);
      return Number.isSafeInteger(numericId) && numericId > 0
        ? String(numericId)
        : undefined;
    },
    [itemsById, serverConversationIds]
  );
  const visibleConversationIds = useMemo(
    () =>
      getVisibleThreadIds(threadIds, threadItems, serverConversationIds)
        .map(resolveRemoteId)
        .filter((id): id is string => Boolean(id)),
    [threadIds, threadItems, serverConversationIds, resolveRemoteId]
  );

  const toggle = useCallback(
    (id: string) => {
      const conversationId = resolveRemoteId(id);
      if (!conversationId) return;
      setSelectedIds((prev) => {
        const next = new Set(prev);
        if (next.has(conversationId)) next.delete(conversationId);
        else next.add(conversationId);
        return next;
      });
    },
    [resolveRemoteId]
  );

  const isSelected = useCallback(
    (id: string) => {
      const conversationId = resolveRemoteId(id);
      return conversationId ? selectedIds.has(conversationId) : false;
    },
    [resolveRemoteId, selectedIds]
  );

  const selectAllVisible = useCallback(() => {
    setSelectedIds((current) => {
      const allSelected =
        visibleConversationIds.length > 0 &&
        visibleConversationIds.every((id) => current.has(id));
      return allSelected ? new Set() : new Set(visibleConversationIds);
    });
  }, [visibleConversationIds]);

  const getAgentGroupSelection = useCallback(
    (agentId: number, visibleIds: readonly string[]) => {
      const completeIds = agentConversationIds.get(agentId);
      const ids =
        completeIds ??
        visibleIds
          .map(resolveRemoteId)
          .filter((id): id is string => Boolean(id));
      return {
        ...getAgentConversationSelectionSummary(selectedIds, ids),
        loading: loadingAgentIds.has(agentId),
        complete: completeIds !== undefined,
      };
    },
    [agentConversationIds, loadingAgentIds, resolveRemoteId, selectedIds]
  );

  const toggleAgentGroup = useCallback(
    async (agentId: number, visibleThreadIds: readonly string[]) => {
      if (loadingAgentIdsRef.current.has(agentId)) return;
      const cachedIds = agentConversationIds.get(agentId);
      if (cachedIds) {
        setSelectedIds((previous) =>
          toggleAgentConversationSelection(previous, cachedIds)
        );
        return;
      }

      const visibleConversationIds = visibleThreadIds
        .map(resolveRemoteId)
        .filter((id): id is string => Boolean(id));
      const shouldSelect =
        visibleConversationIds.length === 0 ||
        !visibleConversationIds.every((id) => selectedIds.has(id));

      loadingAgentIdsRef.current.add(agentId);
      setLoadingAgentIds((previous) => new Set(previous).add(agentId));
      try {
        const boundaries = getConversationDateBoundaries();
        const conversationIds = await fetchAgentConversationIds(
          agentId,
          (offset, limit) =>
            conversationService.getList({
              offset,
              limit,
              ...boundaries,
              conversationType,
            }),
          100
        );
        setAgentConversationIds((previous) => {
          const next = new Map(previous);
          next.set(agentId, conversationIds);
          return next;
        });
        setSelectedIds((previous) =>
          setAgentConversationSelection(previous, conversationIds, shouldSelect)
        );
      } catch (error) {
        log.error(
          `[ThreadList] Failed to load conversations for agent ${agentId}:`,
          error
        );
        message.error(t("chat.threadList.agentSelectionFailed"));
      } finally {
        loadingAgentIdsRef.current.delete(agentId);
        setLoadingAgentIds((previous) => {
          const next = new Set(previous);
          next.delete(agentId);
          return next;
        });
      }
    },
    [agentConversationIds, conversationType, resolveRemoteId, selectedIds, t]
  );

  const clear = useCallback(() => setSelectedIds(new Set()), []);

  const enter = useCallback(() => {
    setSelectedIds(new Set());
    setBatchMode(true);
  }, []);

  const exit = useCallback(() => {
    setBatchMode(false);
    setSelectedIds(new Set());
  }, []);

  const deleteSelected = useCallback(() => {
    const conversationIds: number[] = [];
    for (const id of selectedIds) {
      const num = Number(id);
      if (Number.isSafeInteger(num) && num > 0) {
        conversationIds.push(num);
      }
    }
    if (conversationIds.length === 0) return;

    // Detect whether the currently active conversation is in the delete set.
    // If so, the main panel must switch to a fresh thread after reload,
    // otherwise it would keep pointing at a now-deleted conversation.
    const activeRemoteId = mainThreadId
      ? resolveRemoteId(mainThreadId)
      : undefined;
    const activeConversationId = Number(activeRemoteId);
    const activeDeleted =
      !!activeRemoteId &&
      Number.isInteger(activeConversationId) &&
      activeConversationId > 0 &&
      conversationIds.includes(activeConversationId);

    confirm({
      title: t("chat.threadList.delete"),
      content: t("chat.threadList.batchConfirmDeletionDescription"),
      onOk: async () => {
        try {
          const result = await conversationService.deleteBatch(conversationIds);
          await aui.threads.reload();
          setAgentConversationIds(new Map());
          if (result?.failed_ids?.length) {
            message.warning(
              t("chat.threadList.batchDeletePartial", {
                failed: result.failed_ids.length,
                total: conversationIds.length,
              })
            );
          }
          if (activeDeleted) {
            await onNewConversation?.();
          }
          setBatchMode(false);
          setSelectedIds(new Set());
        } catch (error) {
          log.error("[ThreadList] Failed to batch delete:", error);
          message.error(t("chatInterface.deleteFailed"));
          throw error;
        }
      },
    });
  }, [
    selectedIds,
    threadItems,
    mainThreadId,
    serverConversationIds,
    resolveRemoteId,
    confirm,
    t,
    aui,
    onNewConversation,
  ]);

  const value = useMemo<BatchSelectionValue>(
    () => ({
      batchMode,
      selectedIds,
      allVisibleSelected:
        visibleConversationIds.length > 0 &&
        visibleConversationIds.every((id) => selectedIds.has(id)),
      someVisibleSelected: visibleConversationIds.some((id) =>
        selectedIds.has(id)
      ),
      toggle,
      isSelected,
      selectAllVisible,
      toggleAgentGroup,
      getAgentGroupSelection,
      clear,
      enter,
      exit,
      deleteSelected,
    }),
    [
      batchMode,
      selectedIds,
      visibleConversationIds,
      toggle,
      isSelected,
      selectAllVisible,
      toggleAgentGroup,
      getAgentGroupSelection,
      clear,
      enter,
      exit,
      deleteSelected,
    ]
  );

  return (
    <BatchSelectionContext.Provider value={value}>
      {children}
    </BatchSelectionContext.Provider>
  );
};

const BatchManageButton: FC = () => {
  const { t } = useTranslation();
  const batchSelection = useBatchSelection();

  if (!batchSelection) return null;

  if (batchSelection.batchMode) {
    return (
      <button
        type="button"
        className="flex h-8 items-center gap-1 rounded-md px-2 text-sm text-[#808080] hover:bg-white/70 hover:text-[#191919]"
        onClick={batchSelection.exit}
      >
        <XIcon className="size-3.5 shrink-0" aria-hidden />
        <span>{t("chat.threadList.cancel")}</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      className="flex h-8 items-center gap-1.5 rounded-md px-2 text-sm text-[#808080] hover:bg-white/70 hover:text-[#191919]"
      onClick={batchSelection.enter}
    >
      <ListChecks className="size-4 shrink-0" aria-hidden />
      <span>{t("chat.threadList.batchManage")}</span>
    </button>
  );
};

export const BatchSidebarFooter: FC = () => {
  const { t } = useTranslation();
  const batchSelection = useBatchSelection()!;
  const {
    batchMode,
    selectedIds,
    allVisibleSelected,
    someVisibleSelected,
    selectAllVisible,
    deleteSelected,
  } = batchSelection;

  if (!batchMode) return null;

  return (
    <div className="flex h-10 items-center justify-between gap-2 border-t border-[#d9d9d9]/60 bg-transparent pl-2 pr-4">
      <div className="relative top-2.5 flex w-full items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Checkbox
            className="!m-0 text-sm text-[#243447]"
            checked={allVisibleSelected}
            indeterminate={someVisibleSelected && !allVisibleSelected}
            onChange={selectAllVisible}
          >
            {t("chat.threadList.selectAll")}
          </Checkbox>
          <span className="whitespace-nowrap text-xs text-[#718096]">
            {t("chat.threadList.selectedCount", { count: selectedIds.size })}
          </span>
        </div>
        <button
          type="button"
          className="flex h-8 shrink-0 items-center gap-1 rounded-md border border-[#ffccc7] px-2 text-sm text-[#ff4d4f] hover:bg-[#fff2f0] disabled:cursor-not-allowed disabled:border-[#ffd6d6] disabled:text-[#ffb3b3]"
          disabled={selectedIds.size === 0}
          onClick={deleteSelected}
        >
          <TrashIcon className="size-3.5" aria-hidden />
          {t("chat.threadList.delete")}
        </button>
      </div>
    </div>
  );
};

type RenameSuccessHandler = (
  threadId: string,
  remoteId: string | undefined,
  title: string
) => void;

interface ThreadListProps {
  serverConversationIds?: ReadonlyMap<string, string>;
  activeThreadId?: string;
  generatedTitles?: ReadonlyMap<string, string>;
  onRenameSuccess?: RenameSuccessHandler;
  searchQuery?: string;
  newChatDesign?: boolean;
}

export const ThreadList: FC<ThreadListProps> = ({
  activeThreadId,
  generatedTitles,
  serverConversationIds,
  onRenameSuccess,
  searchQuery = "",
  newChatDesign = false,
}) => {
  const { t } = useTranslation();
  const [completedConversations, setCompletedConversations] = useState(
    () => new Set<string>()
  );
  const isThreadRunning = useAuiState((s) => s.thread.isRunning);
  const mainThreadId = useAuiState((s) => s.threads.mainThreadId);
  const runningThreadId = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (isThreadRunning) {
      runningThreadId.current = mainThreadId;
      return;
    }

    if (runningThreadId.current) {
      const completedThreadId = runningThreadId.current;
      setCompletedConversations((previous) => {
        const next = new Set(previous);
        next.add(completedThreadId);
        return next;
      });
      runningThreadId.current = undefined;
    }
  }, [isThreadRunning, mainThreadId]);
  const isLoading = useAuiState((s) => s.threads.isLoading);
  const isLoadingMore = useAuiState((s) => s.threads.isLoadingMore);
  const hasMore = useAuiState((s) => s.threads.hasMore);
  const threadIds = useAuiState((state) => state.threads.threadIds);
  const threadItems = useAuiState((state) => state.threads.threadItems);
  const visibleThreadIds = getVisibleThreadIds(
    threadIds,
    threadItems,
    serverConversationIds
  );
  const [expandedAgentKeys, setExpandedAgentKeys] = useState<Set<string>>(
    () => new Set()
  );
  const toggleAgentExpanded = useCallback((key: string) => {
    setExpandedAgentKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  return (
    <div className="flex flex-col p-2">
      <div className="mb-1 flex h-8 items-center justify-between px-3 pt-1">
        <p className="text-sm text-muted-foreground">
          {t("chat.threadList.recentConversations")}
        </p>
        <BatchManageButton />
      </div>
      <AuiIf condition={(s) => s.threads.isLoading}>
        <ThreadListSkeleton />
      </AuiIf>
      <AuiIf
        condition={(s) => !s.threads.isLoading && visibleThreadIds.length === 0}
      >
        <ThreadListEmpty />
      </AuiIf>
      <AuiIf
        condition={(s) => !s.threads.isLoading && visibleThreadIds.length > 0}
      >
        <ThreadListItems
          activeThreadId={activeThreadId}
          visibleThreadIds={visibleThreadIds}
          completedConversations={completedConversations}
          generatedTitles={generatedTitles}
          onRenameSuccess={onRenameSuccess}
          searchQuery={searchQuery}
          newChatDesign={newChatDesign}
          expandedAgentKeys={expandedAgentKeys}
          onToggleAgentExpanded={toggleAgentExpanded}
        />
      </AuiIf>
      {hasMore && !isLoading && (
        <ThreadListPrimitive.LoadMore
          disabled={isLoadingMore}
          className="mt-1 flex h-8 w-full items-center justify-center gap-2 rounded-lg px-3 text-xs text-muted-foreground hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoadingMore ? <ArrowDownIcon className="size-3.5" /> : null}
          <span>
            {isLoadingMore
              ? t("chat.threadList.loadingMore")
              : t("chat.threadList.loadMore")}
          </span>
        </ThreadListPrimitive.LoadMore>
      )}
    </div>
  );
};

const ThreadListEmpty: FC = () => {
  const { t } = useTranslation();
  return (
    <div className="space-y-1 px-2 pb-4">
      <div className="flex items-center px-3 py-2 text-left text-muted-foreground">
        <Clock className="mr-2 h-5 w-5" />
        {t("chat.threadList.noHistory")}
      </div>
    </div>
  );
};

interface ThreadListItemsProps {
  visibleThreadIds: string[];
  activeThreadId?: string;
  completedConversations: Set<string>;
  generatedTitles?: ReadonlyMap<string, string>;
  onRenameSuccess?: RenameSuccessHandler;
  searchQuery?: string;
  newChatDesign: boolean;
  expandedAgentKeys: ReadonlySet<string>;
  onToggleAgentExpanded: (key: string) => void;
}

const ThreadListItems: FC<ThreadListItemsProps> = ({
  activeThreadId,
  visibleThreadIds,
  completedConversations,
  generatedTitles,
  onRenameSuccess,
  searchQuery = "",
  newChatDesign,
  expandedAgentKeys,
  onToggleAgentExpanded,
}) => {
  const { t } = useTranslation();

  const agentGroups = useThreadListAgentGroups(
    searchQuery,
    newChatDesign,
    generatedTitles,
    visibleThreadIds
  );
  const timeGroups = useThreadListGroups(
    generatedTitles,
    searchQuery,
    visibleThreadIds
  );
  const pinned = usePinnedThreads();
  const batch = useBatchSelection();

  const GroupedThreadListItem = useMemo<FC>(
    () =>
      function GroupedThreadListItem() {
        return (
          <ThreadListItem
            completedConversations={completedConversations}
            generatedTitles={generatedTitles}
            onRenameSuccess={onRenameSuccess}
            newChatDesign={newChatDesign}
          />
        );
      },
    [completedConversations, generatedTitles, newChatDesign, onRenameSuccess]
  );

  const TimeGroupThreadListItem = useMemo<FC>(
    () =>
      function TimeGroupThreadListItem() {
        return (
          <ThreadListItem
            completedConversations={completedConversations}
            generatedTitles={generatedTitles}
            onRenameSuccess={onRenameSuccess}
            variant="time"
          />
        );
      },
    [completedConversations, generatedTitles, newChatDesign, onRenameSuccess]
  );

  // Workbench (and legacy) sidebar: recency buckets (Today / Last 7 Days /
  // Older) with pinned conversations hoisted into a dedicated top group.
  if (!newChatDesign) {
    if (!timeGroups) {
      return (
        <ThreadListPrimitive.Items>
          {() => (
            <ThreadListItem
              completedConversations={completedConversations}
              generatedTitles={generatedTitles}
              onRenameSuccess={onRenameSuccess}
            />
          )}
        </ThreadListPrimitive.Items>
      );
    }
    if (timeGroups.length === 0) {
      return (
        <div className="flex items-center px-3 py-4 text-sm text-muted-foreground">
          {t("chat.threadList.noSearchResults")}
        </div>
      );
    }
    return (
      <div className="flex flex-col">
        {timeGroups.map((group, groupIndex) => (
          <Fragment key={group.label}>
            {group.label !== "chat.threadList.recentConversations" && (
              <div
                data-slot="aui_thread-list-group-label"
                className="px-3 pt-3 pb-1 text-sm text-muted-foreground"
              >
                {t(group.label)}
              </div>
            )}
            {group.entries.map(({ id, index }) => (
              <ThreadListPrimitive.ItemByIndex
                key={id}
                index={index}
                components={{ ThreadListItem: TimeGroupThreadListItem }}
              />
            ))}
            {group.label === "chat.threadList.pinned" &&
              groupIndex < timeGroups.length - 1 && (
                <div
                  role="separator"
                  className="mx-3 my-2 border-t border-dashed border-gray-400/60 dark:border-gray-500/70"
                />
              )}
          </Fragment>
        ))}
      </div>
    );
  }

  if (!agentGroups) {
    return (
      <ThreadListPrimitive.Items>
        {() => (
          <ThreadListItem
            completedConversations={completedConversations}
            generatedTitles={generatedTitles}
            onRenameSuccess={onRenameSuccess}
            newChatDesign
          />
        )}
      </ThreadListPrimitive.Items>
    );
  }

  if (agentGroups.length === 0) {
    return (
      <div className="flex items-center px-3 py-4 text-sm text-muted-foreground">
        {t("chat.threadList.noSearchResults")}
      </div>
    );
  }

  // Render each thread by index so we can interleave agent group headers
  // between items without giving up the runtime's per-item context.
  // Collapsed groups retain only the open conversation; inactive groups hide
  // every conversation. Expanding a group reveals all of its conversations.
  return (
    <div className="flex flex-col">
      {agentGroups.map((group) => {
        const agentId = group.agentId;
        const groupKey = String(group.agentId ?? "none");
        const entries = pinned
          ? [...group.entries].sort(
              (left, right) =>
                Number(pinned.pinnedIds.has(right.id)) -
                Number(pinned.pinnedIds.has(left.id))
            )
          : group.entries;
        const isExpanded = expandedAgentKeys.has(groupKey);
        const visibleEntries = getVisibleAgentThreads(
          entries,
          isExpanded,
          activeThreadId,
          generatedTitles
        );
        const groupSelection =
          batch?.batchMode && agentId !== null
            ? batch.getAgentGroupSelection(
                agentId,
                entries.map((entry) => entry.id)
              )
            : null;
        const groupLabel = (
          <>
            <LayoutGrid
              className="size-5 shrink-0 text-[#191919]"
              aria-hidden
            />
            <span className="min-w-0 truncate">{group.agentName}</span>
            <ChevronRight
              className={`h-3.5 w-0 shrink-0 overflow-hidden text-[#808080] opacity-0 transition-all duration-200 group-hover:w-3.5 group-hover:opacity-100 group-focus-visible:w-3.5 group-focus-visible:opacity-100${isExpanded ? " rotate-90" : ""}`}
              aria-hidden
            />
          </>
        );

        return (
          <Fragment key={groupKey}>
            {groupSelection && agentId !== null ? (
              <div className="flex h-10 items-center gap-1 rounded-lg px-1 hover:bg-white/70">
                <Checkbox
                  aria-label={t("chat.threadList.selectAgentConversations", {
                    agent: group.agentName,
                  })}
                  checked={groupSelection.checked}
                  indeterminate={groupSelection.indeterminate}
                  disabled={groupSelection.loading}
                  onChange={() =>
                    void batch?.toggleAgentGroup(
                      agentId,
                      entries.map((entry) => entry.id)
                    )
                  }
                />
                <button
                  type="button"
                  data-slot="aui_thread-list-group-label"
                  className="group flex h-full min-w-0 flex-1 items-center gap-3 rounded-lg px-2 text-left text-[14px] text-[#191919]"
                  onClick={() => onToggleAgentExpanded(groupKey)}
                  aria-expanded={isExpanded}
                >
                  {groupLabel}
                </button>
                {groupSelection.loading ? (
                  <LoaderCircle
                    aria-hidden
                    className="size-3.5 shrink-0 animate-spin text-[#808080]"
                  />
                ) : (
                  groupSelection.complete && (
                    <span className="shrink-0 pr-2 text-xs text-[#1677ff]">
                      {groupSelection.selectedCount}/{groupSelection.totalCount}
                    </span>
                  )
                )}
              </div>
            ) : (
              <button
                type="button"
                data-slot="aui_thread-list-group-label"
                className="group flex h-10 items-center gap-3 rounded-lg px-3 text-left text-[14px] text-[#191919] hover:bg-white/70"
                onClick={() => onToggleAgentExpanded(groupKey)}
                aria-expanded={isExpanded}
              >
                {groupLabel}
              </button>
            )}
            {visibleEntries.map(({ id, index }, entryIndex) => (
              <Fragment key={id}>
                {entryIndex > 0 &&
                  pinned?.pinnedIds.has(visibleEntries[entryIndex - 1].id) &&
                  !pinned.pinnedIds.has(id) && (
                    <div
                      role="separator"
                      className="ml-8 mr-3 my-2 border-t border-dashed border-gray-400/60 dark:border-gray-500/70"
                    />
                  )}
                <ThreadListPrimitive.ItemByIndex
                  index={index}
                  components={{ ThreadListItem: GroupedThreadListItem }}
                />
              </Fragment>
            ))}
          </Fragment>
        );
      })}
    </div>
  );
};

type ThreadListGroupEntry = {
  id: string;
  index: number;
  hasRemoteId: boolean;
  isRunning: boolean;
};

type AgentThreadGroup = {
  agentId: number | null;
  agentName: string;
  entries: ThreadListGroupEntry[];
};

// Group the current thread list by agent (conversation history), ordered by
// initial conversation recency, preserving agent order thereafter. Threads without an agent fall into a
// trailing generic bucket. When searchQuery is set, only conversations whose
// title matches (or agents whose name matches) are kept.
const useThreadListAgentGroups = (
  searchQuery: string,
  newChatDesign: boolean,
  generatedTitles: ReadonlyMap<string, string> | undefined,
  visibleThreadIds: readonly string[]
): AgentThreadGroup[] | null => {
  const { t } = useTranslation();
  const threadIds = useAuiState((s) => s.threads.threadIds);
  const threadItems = useAuiState((s) => s.threads.threadItems);
  const { availableMainAgents } = usePublishedAgentList({
    enabled: newChatDesign,
  });
  // Brand-new conversations bind their agent via this registry until the
  // backend conversation list carries the agent_id after the first run.
  const threadAgentOverrides = useThreadAgentOverrides();
  const agentOrderRef = useRef(new Map<number | null, number>());

  const groups = useMemo<AgentThreadGroup[] | null>(() => {
    const itemsById = new Map(
      (
        threadItems as ReadonlyArray<{
          id: string;
          title?: string;
          remoteId?: string;
          isRunning?: boolean;
          custom?: { lastMessageAt?: string; agentId?: number | string };
        }>
      ).map((item) => [item.id, item])
    );
    const dates: (Date | undefined)[] = threadIds.map((id) => {
      const raw = itemsById.get(id)?.custom?.lastMessageAt;
      return raw ? new Date(raw) : undefined;
    });
    const agentNameById = new Map<number, string>();
    for (const agent of availableMainAgents) {
      const published = agent as unknown as PublishedAgent;
      agentNameById.set(
        published.agent_id,
        published.display_name || published.name
      );
    }

    const time = (index: number) =>
      dates[index]?.getTime() ?? Number.MAX_SAFE_INTEGER;
    const indices = threadIds
      .map((_, index) => index)
      .filter((index) => visibleThreadIds.includes(threadIds[index]))
      .sort((a, b) => time(b) - time(a));

    const query = searchQuery.trim().toLowerCase();
    const groups: AgentThreadGroup[] = [];
    const groupByAgent = new Map<number | null, AgentThreadGroup>();
    for (const index of indices) {
      const item = itemsById.get(threadIds[index]);
      const agentId = resolveThreadAgentId(
        item?.custom?.agentId,
        threadAgentOverrides[threadIds[index]]
      );
      let group = groupByAgent.get(agentId);
      if (!group) {
        group = {
          agentId,
          agentName:
            agentId !== null
              ? (agentNameById.get(agentId) ?? `#${agentId}`)
              : t("chat.threadList.recentConversations"),
          entries: [],
        };
        groupByAgent.set(agentId, group);
        groups.push(group);
      }
      if (query) {
        const agentNameMatch = group.agentName.toLowerCase().includes(query);
        const threadTitle =
          (
            generatedTitles?.get(threadIds[index]) ?? item?.title
          )?.toLowerCase() ?? "";
        if (!agentNameMatch && !threadTitle.includes(query)) {
          continue;
        }
      }
      group.entries.push({
        id: threadIds[index],
        index,
        hasRemoteId: Boolean(itemsById.get(threadIds[index])?.remoteId),
        isRunning: item?.isRunning === true,
      });
    }
    for (const group of groups) {
      if (!agentOrderRef.current.has(group.agentId)) {
        agentOrderRef.current.set(group.agentId, agentOrderRef.current.size);
      }
    }
    groups.sort((a, b) => {
      if (a.agentId === null) return b.agentId === null ? 0 : 1;
      if (b.agentId === null) return -1;
      return (
        agentOrderRef.current.get(a.agentId)! -
        agentOrderRef.current.get(b.agentId)!
      );
    });
    if (query) {
      return groups.filter((group) => group.entries.length > 0);
    }
    return groups;
  }, [
    threadIds,
    threadItems,
    availableMainAgents,
    threadAgentOverrides,
    generatedTitles,
    t,
    searchQuery,
    newChatDesign,
    visibleThreadIds,
  ]);
  return newChatDesign ? groups : null;
};

const DAY_IN_MS = 86_400_000;

type ThreadTimeGroupEntry = { id: string; index: number };

type ThreadTimeGroup = {
  label: string;
  entries: ThreadTimeGroupEntry[];
};

// Bucket a date into one of three recency groups (Today / Last 7 Days / Older)
// using the day boundaries of the user's local timezone.
const dateGroupLabel = (
  date: Date | undefined,
  startOfToday: number
): string => {
  if (!date || date.getTime() >= startOfToday) return "chat.threadList.today";
  if (date.getTime() >= startOfToday - 7 * DAY_IN_MS) {
    return "chat.threadList.last7Days";
  }
  return "chat.threadList.older";
};

// Build ordered recency groups for the workbench sidebar. Returns null when
// no thread has a usable timestamp so the caller can render a flat list.
// When a search query is present, entries are filtered by title first; an
// empty result yields an empty group list so the caller renders nothing.
const useThreadListGroups = (
  generatedTitles: ReadonlyMap<string, string> | undefined,
  searchQuery: string,
  visibleThreadIds: readonly string[]
): ThreadTimeGroup[] | null => {
  const threadIds = useAuiState((s) => s.threads.threadIds);
  const threadItems = useAuiState((s) => s.threads.threadItems);
  const pinned = usePinnedThreads();

  return useMemo<ThreadTimeGroup[] | null>(() => {
    const itemsById = new Map(
      (
        threadItems as ReadonlyArray<{
          id: string;
          title?: string;
          remoteId?: string;
          custom?: { lastMessageAt?: string };
        }>
      ).map((item) => [item.id, item])
    );
    const query = searchQuery.trim().toLowerCase();
    const titles = threadIds.map((id) =>
      (generatedTitles?.get(id) ?? itemsById.get(id)?.title ?? "").toLowerCase()
    );
    const matches = threadIds.map(
      (_, index) => !query || titles[index].includes(query)
    );
    if (query && !matches.some(Boolean)) return [];

    const pinOrder = pinned?.getPinOrder;
    const getPinOrder = pinOrder
      ? ({ id }: ThreadTimeGroupEntry) => pinOrder(itemsById.get(id) ?? { id })
      : undefined;

    const dates: (Date | undefined)[] = threadIds.map((id) => {
      const raw = itemsById.get(id)?.custom?.lastMessageAt;
      return raw ? new Date(raw) : undefined;
    });
    if (!dates.some(Boolean)) {
      // No usable timestamps: keep the flat-list fallback for the unfiltered
      // view, and bucket search matches under a single label when filtering.
      return hoistPinnedThreads(
        [
          {
            label: "chat.threadList.recentConversations",
            entries: threadIds
              .map((id, index) => ({ id, index }))
              .filter(
                (_, index) =>
                  matches[index] && visibleThreadIds.includes(threadIds[index])
              ),
          },
        ],
        ({ id }) => pinned?.isPinned(itemsById.get(id) ?? { id }) ?? false,
        getPinOrder
      );
    }

    const now = new Date();
    const startOfToday = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate()
    ).getTime();

    const time = (index: number) =>
      dates[index]?.getTime() ?? Number.MAX_SAFE_INTEGER;
    const indices = threadIds
      .map((_, index) => index)
      .filter(
        (_, index) =>
          matches[index] && visibleThreadIds.includes(threadIds[index])
      )
      .sort((a, b) => time(b) - time(a));

    const result: ThreadTimeGroup[] = [];
    for (const index of indices) {
      const label = dateGroupLabel(dates[index], startOfToday);
      const entry: ThreadTimeGroupEntry = { id: threadIds[index], index };
      const lastGroup = result[result.length - 1];
      if (lastGroup?.label === label) {
        lastGroup.entries.push(entry);
      } else {
        result.push({ label, entries: [entry] });
      }
    }

    return hoistPinnedThreads(
      result,
      ({ id }) => pinned?.isPinned(itemsById.get(id) ?? { id }) ?? false,
      getPinOrder
    );
  }, [
    threadIds,
    threadItems,
    generatedTitles,
    searchQuery,
    pinned,
    visibleThreadIds,
  ]);
};

const ThreadListSkeleton: FC = () => {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <div
          key={i}
          role="status"
          aria-label={t("chat.threadList.loading")}
          data-slot="aui_thread-list-skeleton-wrapper"
          className="flex h-8 items-center px-2.5"
        >
          <Skeleton
            data-slot="aui_thread-list-skeleton"
            className="h-3.5 w-full"
          />
        </div>
      ))}
    </div>
  );
};

interface ThreadListItemProps {
  completedConversations: Set<string>;
  generatedTitles?: ReadonlyMap<string, string>;
  onRenameSuccess?: RenameSuccessHandler;
  newChatDesign?: boolean;
}

// Relative time for conversation rows, e.g. "20分钟前" / "20m ago".
const formatRelativeTime = (
  lastMessageAt: string | undefined,
  t: (key: string, options?: Record<string, unknown>) => string
): string => {
  if (!lastMessageAt) return "";
  const elapsedMs = Date.now() - new Date(lastMessageAt).getTime();
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0) return "";
  const minutes = Math.floor(elapsedMs / 60_000);
  if (minutes < 1) return t("chat.threadList.justNow");
  if (minutes < 60) return t("chat.threadList.minutesAgo", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("chat.threadList.hoursAgo", { count: hours });
  const days = Math.floor(hours / 24);
  return t("chat.threadList.daysAgo", { count: days });
};

const ThreadListItem: FC<
  ThreadListItemProps & { variant?: "agent" | "time" }
> = ({
  completedConversations,
  generatedTitles,
  onRenameSuccess,
  newChatDesign = false,
  variant = "agent",
}) => {
  const thread = useAuiState((s) => s.threadListItem);
  const pinned = usePinnedThreads();
  const isPinned = pinned?.isPinned(thread) ?? false;

  return (
    <ThreadListItemPrimitive.Root
      data-pinned={isPinned || undefined}
      className={
        variant === "time"
          ? "group/item flex h-10 items-center gap-2 rounded-lg px-2 py-2 hover:bg-white data-[active=true]:bg-white"
          : "group/item flex h-10 items-center rounded-lg hover:bg-white/70 data-[active=true]:bg-white"
      }
    >
      <ThreadListItemContent
        completedConversations={completedConversations}
        generatedTitles={generatedTitles}
        onRenameSuccess={onRenameSuccess}
        variant={variant}
        newChatDesign={newChatDesign}
      />
    </ThreadListItemPrimitive.Root>
  );
};

interface ThreadListItemContentProps {
  completedConversations: Set<string>;
  generatedTitles?: ReadonlyMap<string, string>;
  onRenameSuccess?: RenameSuccessHandler;
  variant?: "agent" | "time";
  newChatDesign: boolean;
}

const ThreadListItemContent: FC<ThreadListItemContentProps> = ({
  completedConversations,
  generatedTitles,
  onRenameSuccess,
  variant = "agent",
  newChatDesign,
}) => {
  const { t } = useTranslation();
  const aui = useAui();
  const { confirm } = useConfirmModal();
  const [isEditing, setIsEditing] = useState(false);
  const batch = useBatchSelection();
  const batchMode = batch?.batchMode ?? false;
  const toggle = batch?.toggle;
  const isSelected = batch?.isSelected;
  const thread = useAui().threadListItem.getState();
  const isRunning = useAuiState((s) => s.threadListItem.isRunning);
  const threadListItem = aui.threadListItem;
  const title =
    generatedTitles?.get(thread.id) ??
    (thread.remoteId ? generatedTitles?.get(thread.remoteId) : undefined) ??
    thread.title ??
    t("chat.thread.newChat");

  const pinned = usePinnedThreads();
  const isPinned = pinned?.isPinned(thread) ?? false;

  const handleRename = async (newTitle: string) => {
    const normalized = newTitle.trim();
    if (!normalized) return;
    setPendingThreadOperationId(thread.id);
    try {
      await threadListItem.rename(normalized);
      onRenameSuccess?.(thread.id, thread.remoteId, normalized);
      setIsEditing(false);
    } catch (error) {
      log.error("[ThreadList] Failed to rename thread:", error);
      message.error(t("chat.threadList.renameFailed"));
    } finally {
      setPendingThreadOperationId(undefined);
    }
  };

  const handleDelete = () => {
    confirm({
      title: t("chat.threadList.delete"),
      content: t("chat.threadList.confirmDeletionDescription"),
      onOk: async () => {
        setPendingThreadOperationId(thread.id);
        try {
          await threadListItem.delete();
          await aui.threads.reload();
        } catch (error) {
          log.error("[ThreadList] Failed to delete thread:", error);
          message.error(t("chatInterface.deleteFailed"));
          throw error;
        } finally {
          setPendingThreadOperationId(undefined);
        }
      },
    });
  };

  const togglePinned = () => pinned?.togglePin(thread);

  const renderMainContent = () => {
    if (isEditing) {
      return (
        <form
          className="flex min-w-0 flex-1 items-center gap-1 px-2"
          onSubmit={(event) => {
            event.preventDefault();
            const value = new FormData(event.currentTarget).get("title");
            if (typeof value === "string") void handleRename(value);
          }}
        >
          <input
            autoFocus
            name="title"
            defaultValue={title}
            aria-label={t("chat.threadList.rename")}
            className="h-8 min-w-0 flex-1 rounded border bg-background px-2 text-sm"
            onKeyDown={(event) => {
              if (event.key === "Escape") setIsEditing(false);
            }}
          />
          <button type="submit" className="text-xs text-primary">
            {t("common.save", { defaultValue: "Save" })}
          </button>
          <button
            type="button"
            className="text-xs text-muted-foreground"
            onClick={() => setIsEditing(false)}
          >
            {t("common.cancel", { defaultValue: "Cancel" })}
          </button>
        </form>
      );
    }
    if (batchMode) {
      return (
        <button
          type="button"
          className={`flex h-full min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-lg px-3 text-left text-sm transition-colors hover:bg-muted ${
            isSelected?.(thread.id) ? "bg-accent" : ""
          }`}
          onClick={() => toggle?.(thread.id)}
        >
          <Checkbox checked={isSelected?.(thread.id) ?? false} />
          <span className="min-w-0 flex-1 truncate text-left">{title}</span>
        </button>
      );
    }
    return (
      <ThreadListItemPrimitive.Trigger
        className={cn(
          variant === "time"
            ? "flex h-10 min-w-0 flex-1 items-center gap-2 text-left text-base leading-6 text-[#191919]"
            : "flex h-10 min-w-0 flex-1 items-center gap-3 pl-8 pr-3 text-left text-[14px] text-[#595959]",
          isPinned && variant === "agent" && "gap-2 pl-3"
        )}
      >
        {isPinned && (
          <PinIcon
            className="size-3 shrink-0 text-blue-500"
            aria-label={t("chat.threadList.pinned")}
          />
        )}
        <div className="flex min-w-0 flex-1 items-center text-left">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="min-w-0 flex-1 truncate text-left">{title}</span>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-80 break-words">
              {title}
            </TooltipContent>
          </Tooltip>
          {!newChatDesign &&
            (variant === "time" ? (
              <ThreadRowEndStatus
                completedConversations={completedConversations}
              />
            ) : (
              <ConversationStatusIndicatorWrapper
                completedConversations={completedConversations}
              />
            ))}
        </div>
        {newChatDesign && isRunning ? (
          <LoaderCircle
            role="status"
            aria-label={t("chat.threadList.running")}
            className="size-3 shrink-0 animate-spin text-[#808080]"
          />
        ) : (
          <span
            className={
              variant === "time"
                ? "shrink-0 whitespace-nowrap text-xs text-muted-foreground group-hover/item:hidden"
                : "shrink-0 text-[14px] leading-[22px] text-[#808080]"
            }
          >
            {formatRelativeTime(
              (thread as { custom?: { lastMessageAt?: string } }).custom
                ?.lastMessageAt,
              t
            )}
          </span>
        )}
      </ThreadListItemPrimitive.Trigger>
    );
  };

  return (
    <>
      {renderMainContent()}
      {!isEditing && !batchMode && (
        <ThreadListItemMorePrimitive.Root>
          <ThreadListItemMorePrimitive.Trigger
            aria-label={t("chat.threadList.moreActions", { title })}
            className="size-7 shrink-0 rounded-md opacity-0 group-hover/item:opacity-100 group-focus-within/item:opacity-100 focus-visible:opacity-100"
          >
            <MoreHorizontalIcon className="size-4" />
          </ThreadListItemMorePrimitive.Trigger>
          <ThreadListItemMorePrimitive.Content className="z-50 rounded-md border bg-popover p-1 shadow-md">
            <ThreadListItemMorePrimitive.Item
              onSelect={togglePinned}
              disabled={!pinned?.canPin(thread)}
              className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
            >
              {isPinned ? (
                <PinOffIcon className="size-4" />
              ) : (
                <PinIcon className="size-4" />
              )}
              {isPinned ? t("chat.threadList.unpin") : t("chat.threadList.pin")}
            </ThreadListItemMorePrimitive.Item>
            <ThreadListItemMorePrimitive.Item
              onSelect={() => setIsEditing(true)}
              className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
            >
              <PencilIcon className="size-4" />
              {t("chat.threadList.rename")}
            </ThreadListItemMorePrimitive.Item>
            <ThreadListItemMorePrimitive.Item
              onSelect={() => setTimeout(handleDelete, 0)}
              className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10"
            >
              <TrashIcon className="size-4" />
              {t("chat.threadList.delete")}
            </ThreadListItemMorePrimitive.Item>
          </ThreadListItemMorePrimitive.Content>
        </ThreadListItemMorePrimitive.Root>
      )}
    </>
  );
};

// Wrapper to get thread status from adapter and pass to status indicator
const ConversationStatusIndicatorWrapper: FC<{
  completedConversations: Set<string>;
}> = ({ completedConversations }) => {
  const aui = useAui();
  const threadId = aui.threadListItem().getState().id;
  const isRunning = useAuiState(
    (state) => state.thread.isRunning && state.threads.mainThreadId === threadId
  );

  return (
    <ConversationStatusIndicator
      isStreaming={isRunning}
      isCompleted={!isRunning && completedConversations.has(threadId)}
    />
  );
};

// End-of-row status icon for the workbench time-group list: running shows an
// inline spinner; an error status (when surfaced) shows an orange alert.
const ThreadRowEndStatus: FC<{ completedConversations: Set<string> }> = ({
  completedConversations,
}) => {
  const aui = useAui();
  const { t } = useTranslation();
  const item = aui.threadListItem().getState();
  const status = item.status as string;
  const runtimeRunning = useAuiState(
    (state) => state.thread.isRunning && state.threads.mainThreadId === item.id
  );
  const isRunning =
    runtimeRunning || status === "running" || status === "streaming";
  const isError = status === "error";

  if (isRunning) {
    return (
      <Loader2Icon
        className="size-4 shrink-0 animate-spin text-muted-foreground"
        aria-hidden
      />
    );
  }
  if (isError) {
    return (
      <CircleAlertIcon className="size-4 shrink-0 text-amber-500" aria-hidden />
    );
  }
  if (completedConversations.has(item.id)) {
    return (
      <span
        className="size-2 shrink-0 rounded-full bg-blue-500"
        title={t("chat.threadList.completed")}
      />
    );
  }
  return null;
};
