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
  MoreVerticalIcon,
  PencilIcon,
  TrashIcon,
  PinIcon,
  PinOffIcon,
  ArrowDownIcon,
  Repeat2Icon,
  XIcon,
  ChevronRight,
  LayoutGrid,
  Loader2Icon,
  CircleAlertIcon,
  LoaderCircle,
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
  toggle: (id: string) => void;
  selectAllVisible: () => void;
  clear: () => void;
  enter: () => void;
  exit: () => void;
  deleteSelected: () => void;
}

const BatchSelectionContext = createContext<BatchSelectionValue | null>(null);

interface PinnedThreadsValue {
  pinnedIds: ReadonlySet<string>;
  togglePin: (id: string) => void;
}

const PinnedThreadsContext = createContext<PinnedThreadsValue | null>(null);
const PINNED_THREADS_STORAGE_KEY = "chat.pinnedThreadIds";

const loadPinnedThreadIds = (): ReadonlySet<string> => {
  if (typeof window === "undefined") return new Set();
  try {
    const parsed: unknown = JSON.parse(
      window.localStorage.getItem(PINNED_THREADS_STORAGE_KEY) || "[]"
    );
    return Array.isArray(parsed)
      ? new Set(
          parsed.filter((value): value is string => typeof value === "string")
        )
      : new Set();
  } catch {
    return new Set();
  }
};

export const PinnedThreadsProvider: FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [pinnedIds, setPinnedIds] =
    useState<ReadonlySet<string>>(loadPinnedThreadIds);
  const togglePin = useCallback((id: string) => {
    setPinnedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      try {
        window.localStorage.setItem(
          PINNED_THREADS_STORAGE_KEY,
          JSON.stringify([...next])
        );
      } catch {
        // Storage failures are non-fatal for local pin state.
      }
      return next;
    });
  }, []);
  const value = useMemo(
    () => ({ pinnedIds, togglePin }),
    [pinnedIds, togglePin]
  );

  return (
    <PinnedThreadsContext.Provider value={value}>
      {children}
    </PinnedThreadsContext.Provider>
  );
};

const usePinnedThreads = (): PinnedThreadsValue | null =>
  useContext(PinnedThreadsContext);

// Safe hook: returns null outside a provider so list items render normally
// (no batch UI) when the sidebar is not wrapped in BatchSelectionProvider.
const useBatchSelection = (): BatchSelectionValue | null =>
  useContext(BatchSelectionContext);

export const BatchSelectionProvider: FC<{
  children: ReactNode;
  onNewConversation?: () => void | Promise<void>;
  serverConversationIds?: ReadonlyMap<string, string>;
}> = ({ children, onNewConversation, serverConversationIds }) => {
  const { t } = useTranslation();
  const aui = useAui();
  const { confirm } = useConfirmModal();
  const threadIds = useAuiState((s) => s.threads.threadIds);
  const threadItems = useAuiState((s) => s.threads.threadItems);
  const mainThreadId = useAuiState((s) => s.threads.mainThreadId);
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());

  const toggle = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAllVisible = useCallback(() => {
    setSelectedIds(
      () =>
        new Set(
          getVisibleThreadIds(threadIds, threadItems, serverConversationIds)
        )
    );
  }, [threadIds, threadItems, serverConversationIds]);

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
    const itemsById = new Map(
      (threadItems as ReadonlyArray<{ id: string; remoteId?: string }>).map(
        (it) => [it.id, it]
      )
    );
    const conversationIds: number[] = [];
    for (const id of selectedIds) {
      const conversationId =
        serverConversationIds?.get(id) || itemsById.get(id)?.remoteId;
      const num = Number(conversationId);
      if (conversationId && Number.isInteger(num) && num > 0) {
        conversationIds.push(num);
      }
    }
    if (conversationIds.length === 0) return;

    // Detect whether the currently active conversation is in the delete set.
    // If so, the main panel must switch to a fresh thread after reload,
    // otherwise it would keep pointing at a now-deleted conversation.
    const activeRemoteId = mainThreadId
      ? serverConversationIds?.get(mainThreadId) ||
        itemsById.get(mainThreadId)?.remoteId
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
    confirm,
    t,
    aui,
    onNewConversation,
  ]);

  const value = useMemo<BatchSelectionValue>(
    () => ({
      batchMode,
      selectedIds,
      toggle,
      selectAllVisible,
      clear,
      enter,
      exit,
      deleteSelected,
    }),
    [
      batchMode,
      selectedIds,
      toggle,
      selectAllVisible,
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

export const BatchSidebarFooter: FC<{ onSwitchToLegacy?: () => void }> = ({
  onSwitchToLegacy,
}) => {
  const { t } = useTranslation();
  const { batchMode, selectedIds, exit, selectAllVisible, deleteSelected } =
    useBatchSelection()!;

  if (batchMode) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between px-1 text-xs text-muted-foreground">
          <span>
            {t("chat.threadList.selectedCount", { count: selectedIds.size })}
          </span>
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={exit}
          >
            {t("chat.threadList.cancel")}
          </button>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="flex h-9 flex-1 items-center justify-center rounded-lg border px-3 text-sm hover:bg-muted"
            onClick={selectAllVisible}
          >
            {t("chat.threadList.selectAll")}
          </button>
          <button
            type="button"
            className="flex h-9 flex-1 items-center justify-center rounded-lg border border-destructive/30 px-3 text-sm text-destructive hover:bg-destructive/10 disabled:opacity-50"
            disabled={selectedIds.size === 0}
            onClick={deleteSelected}
          >
            {t("chat.threadList.delete")}
          </button>
        </div>
      </div>
    );
  }

  if (!onSwitchToLegacy) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <button
        type="button"
        className="flex h-9 w-full items-center justify-center gap-2 rounded-lg border px-3 text-sm hover:bg-muted bg-white"
        onClick={onSwitchToLegacy}
      >
        <Repeat2Icon className="size-4 shrink-0" />
        <span>{t("chat.sidebar.switchToLegacy")}</span>
      </button>
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
    <div className="space-y-1 px-2 py-4">
      <p className="px-2 text-sm font-medium text-muted-foreground">
        {t("chat.threadList.recentConversations")}
      </p>
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
            <div
              data-slot="aui_thread-list-group-label"
              // The first group sits right under the new-conversation button;
              // keep it closer to avoid a large empty band below the header.
              className={cn(
                "px-3 pb-1 text-sm text-muted-foreground",
                groupIndex === 0 ? "pt-0" : "pt-3"
              )}
            >
              {t(group.label)}
            </div>
            {group.entries.map(({ id, index }) => (
              <ThreadListPrimitive.ItemByIndex
                key={id}
                index={index}
                components={{ ThreadListItem: TimeGroupThreadListItem }}
              />
            ))}
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
      <div className="px-3 pb-1 pt-2 text-[14px] text-[#808080]">
        {t("chat.threadList.recentConversations")}
      </div>
      {agentGroups.map((group) => {
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
        return (
          <Fragment key={groupKey}>
            <button
              type="button"
              data-slot="aui_thread-list-group-label"
              className="group flex h-10 items-center gap-3 rounded-lg px-3 text-left text-[14px] text-[#191919] hover:bg-white/70"
              onClick={() => onToggleAgentExpanded(groupKey)}
              aria-expanded={isExpanded}
            >
              <LayoutGrid
                className="size-5 shrink-0 text-[#191919]"
                aria-hidden
              />
              <span className="min-w-0 truncate">{group.agentName}</span>
              <ChevronRight
                className={`h-3.5 w-0 shrink-0 overflow-hidden text-[#808080] opacity-0 transition-all duration-200 group-hover:w-3.5 group-hover:opacity-100 group-focus-visible:w-3.5 group-focus-visible:opacity-100${isExpanded ? " rotate-90" : ""}`}
                aria-hidden
              />
            </button>
            {visibleEntries.map(({ id, index }) => (
              <ThreadListPrimitive.ItemByIndex
                key={id}
                index={index}
                components={{ ThreadListItem: GroupedThreadListItem }}
              />
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
  const pinnedIds = pinned?.pinnedIds;

  return useMemo<ThreadTimeGroup[] | null>(() => {
    const itemsById = new Map(
      (
        threadItems as ReadonlyArray<{
          id: string;
          title?: string;
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

    const dates: (Date | undefined)[] = threadIds.map((id) => {
      const raw = itemsById.get(id)?.custom?.lastMessageAt;
      return raw ? new Date(raw) : undefined;
    });
    if (!dates.some(Boolean)) {
      // No usable timestamps: keep the flat-list fallback for the unfiltered
      // view, and bucket search matches under a single label when filtering.
      return [
        {
          label: "chat.threadList.recentConversations",
          entries: threadIds
            .map((id, index) => ({ id, index }))
            .filter(
              (_, index) =>
                matches[index] && visibleThreadIds.includes(threadIds[index])
            ),
        },
      ];
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

    // Hoist locally pinned conversations into a dedicated top group.
    if (pinnedIds && pinnedIds.size > 0) {
      const pinnedGroup: ThreadTimeGroup = {
        label: "chat.threadList.pinned",
        entries: [],
      };
      const remaining: ThreadTimeGroup[] = [];
      for (const group of result) {
        const kept = group.entries.filter((entry) => pinnedIds.has(entry.id));
        const others = group.entries.filter(
          (entry) => !pinnedIds.has(entry.id)
        );
        pinnedGroup.entries.push(...kept);
        if (others.length > 0) remaining.push({ ...group, entries: others });
      }
      if (pinnedGroup.entries.length > 0) {
        return [pinnedGroup, ...remaining];
      }
    }
    return result;
  }, [
    threadIds,
    threadItems,
    generatedTitles,
    searchQuery,
    pinnedIds,
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
  return (
    <ThreadListItemPrimitive.Root
      className={
        variant === "time"
          ? // Drop the row's right padding so the trailing timestamp lines up
            // with the header collapse trigger near the panel edge.
            "group/item relative flex h-10 items-center gap-2 rounded-lg pl-2 py-2 hover:bg-[rgba(25,25,25,0.03)] active:bg-[rgba(25,25,25,0.05)] data-[active=true]:bg-[rgba(25,25,25,0.05)]"
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
  const selectedIds = batch?.selectedIds;
  const toggle = batch?.toggle;
  const thread = useAui().threadListItem.getState();
  const isRunning = useAuiState((s) => s.threadListItem.isRunning);
  const threadListItem = aui.threadListItem;
  const title =
    generatedTitles?.get(thread.id) ??
    (thread.remoteId ? generatedTitles?.get(thread.remoteId) : undefined) ??
    thread.title ??
    t("chat.thread.newChat");

  const pinned = usePinnedThreads();
  const isPinned = pinned?.pinnedIds.has(thread.id) ?? false;

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

  const togglePinned = () => pinned?.togglePin(thread.id);

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
          className={`flex min-w-0 flex-1 cursor-pointer items-center gap-2 px-3 text-left text-sm transition-colors hover:bg-muted ${
            selectedIds?.has(thread.id) ? "bg-accent" : ""
          }`}
          onClick={() => toggle?.(thread.id)}
        >
          <Checkbox checked={selectedIds?.has(thread.id) ?? false} />
          <span className="min-w-0 flex-1 truncate text-left">{title}</span>
        </button>
      );
    }
    return (
      <ThreadListItemPrimitive.Trigger
        className={
          variant === "time"
            ? "flex h-10 min-w-0 flex-1 items-center gap-2 text-left text-base leading-6 text-[#191919]"
            : "flex h-10 min-w-0 flex-1 items-center gap-3 pl-8 pr-3 text-left text-[14px] text-[#595959]"
        }
      >
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
              <ThreadRowEndStatus />
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
            ) ||
              // Conversations created in this session have no server timestamp
              // yet; show "just now" once their first run completes instead of
              // leaving the time slot empty.
              (completedConversations.has(thread.id)
                ? t("chat.threadList.justNow")
                : "")}
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
            className={
              variant === "time"
                ? // The invisible-in-idle actions button must not reserve row
                  // space, otherwise the timestamp cannot sit flush with the
                  // row edge; it overlays the timestamp spot on hover.
                  "absolute right-0 top-1/2 size-7 -translate-y-1/2 rounded-md opacity-0 group-hover/item:opacity-100"
                : "size-7 shrink-0 rounded-md opacity-0 group-hover/item:opacity-100"
            }
          >
            <MoreVerticalIcon className="size-4" />
          </ThreadListItemMorePrimitive.Trigger>
          <ThreadListItemMorePrimitive.Content className="z-50 rounded-md border bg-popover p-1 shadow-md">
            <ThreadListItemMorePrimitive.Item
              onSelect={togglePinned}
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
const ThreadRowEndStatus: FC = () => {
  const aui = useAui();
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
  return null;
};
