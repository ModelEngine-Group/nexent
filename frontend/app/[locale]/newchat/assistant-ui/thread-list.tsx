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
  CheckIcon,
  XIcon,
  ChevronRight,
  LayoutGrid,
  Loader2Icon,
  CircleAlertIcon,
} from "lucide-react";
import {
  Fragment,
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import log from "@/lib/logger";
import { conversationService } from "@/services/conversationService";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useThreadAgentOverrides } from "../adapter/thread-agent-registry";
import type { PublishedAgent } from "@/types/agentConfig";
import type { FC } from "react";
import { setPendingThreadOperationId } from "../adapter/conversation-thread-list-adapter";

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
}> = ({ children, onNewConversation }) => {
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
    setSelectedIds(() => new Set(threadIds));
  }, [threadIds]);

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
      const remoteId = itemsById.get(id)?.remoteId;
      const num = Number(remoteId);
      if (remoteId && Number.isInteger(num) && num > 0) {
        conversationIds.push(num);
      }
    }
    if (conversationIds.length === 0) return;

    // Detect whether the currently active conversation is in the delete set.
    // If so, the main panel must switch to a fresh thread after reload,
    // otherwise it would keep pointing at a now-deleted conversation.
    const activeRemoteId = mainThreadId
      ? itemsById.get(mainThreadId)?.remoteId
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

interface ThreadListProps {
  generatedTitles?: ReadonlyMap<string, string>;
  searchQuery?: string;
  newChatDesign?: boolean;
}

export const ThreadList: FC<ThreadListProps> = ({
  generatedTitles,
  searchQuery = "",
  newChatDesign = false,
}) => {
  const { t } = useTranslation();
  const completedConversations = useMemo(() => new Set<string>(), []);
  const isLoading = useAuiState((s) => s.threads.isLoading);
  const isLoadingMore = useAuiState((s) => s.threads.isLoadingMore);
  const hasMore = useAuiState((s) => s.threads.hasMore);

  return (
    <div className="flex flex-col px-4 py-2">
      <AuiIf condition={(s) => s.threads.isLoading}>
        <ThreadListSkeleton />
      </AuiIf>
      <AuiIf
        condition={(s) =>
          !s.threads.isLoading && s.threads.threadIds.length === 0
        }
      >
        <ThreadListEmpty />
      </AuiIf>
      <AuiIf
        condition={(s) =>
          !s.threads.isLoading && s.threads.threadIds.length > 0
        }
      >
        <ThreadListItems
          completedConversations={completedConversations}
          generatedTitles={generatedTitles}
          searchQuery={searchQuery}
          newChatDesign={newChatDesign}
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
  completedConversations: Set<string>;
  generatedTitles?: ReadonlyMap<string, string>;
  searchQuery?: string;
  newChatDesign: boolean;
}

const ThreadListItems: FC<ThreadListItemsProps> = ({
  completedConversations,
  generatedTitles,
  searchQuery = "",
  newChatDesign,
}) => {
  const { t } = useTranslation();

  const agentGroups = useThreadListAgentGroups(searchQuery, newChatDesign);
  const timeGroups = useThreadListGroups(generatedTitles, searchQuery);
  const pinned = usePinnedThreads();
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

  const GroupedThreadListItem = useMemo<FC>(
    () =>
      function GroupedThreadListItem() {
        return (
          <ThreadListItem
            completedConversations={completedConversations}
            generatedTitles={generatedTitles}
          />
        );
      },
    [completedConversations, generatedTitles]
  );

  const TimeGroupThreadListItem = useMemo<FC>(
    () =>
      function TimeGroupThreadListItem() {
        return (
          <ThreadListItem
            completedConversations={completedConversations}
            generatedTitles={generatedTitles}
            variant="time"
          />
        );
      },
    [completedConversations, generatedTitles]
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
        {timeGroups.map((group) => (
          <Fragment key={group.label}>
            <div
              data-slot="aui_thread-list-group-label"
              className="px-3 pt-3 pb-1 text-sm text-muted-foreground"
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
  // Each agent group is collapsed by default and only shows its most recent
  // conversation; expanding the group reveals every conversation.
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
        const visibleEntries = isExpanded
          ? entries
          : (newChatDesign
              ? entries.filter((entry) => entry.hasRemoteId)
              : entries
            ).slice(0, 1);
        return (
          <Fragment key={groupKey}>
            <button
              type="button"
              data-slot="aui_thread-list-group-label"
              className="flex h-10 items-center gap-3 px-3 text-left text-[14px] text-[#191919] hover:bg-white/70"
              onClick={() => toggleAgentExpanded(groupKey)}
              aria-expanded={isExpanded}
            >
              <LayoutGrid
                className="size-5 shrink-0 text-[#191919]"
                aria-hidden
              />
              <span className="min-w-0 truncate">{group.agentName}</span>
              {!isExpanded && (
                <ChevronRight
                  className="size-3.5 shrink-0 text-[#808080]"
                  aria-hidden
                />
              )}
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

type ThreadListGroupEntry = { id: string; index: number; hasRemoteId: boolean };

type AgentThreadGroup = {
  agentId: number | null;
  agentName: string;
  entries: ThreadListGroupEntry[];
};

// Group the current thread list by agent (conversation history), ordered by
// each agent's most recent conversation. Threads without an agent fall into a
// trailing generic bucket. When searchQuery is set, only conversations whose
// title matches (or agents whose name matches) are kept. Returns null when no
// thread has a usable timestamp so the caller can render a flat list.
const useThreadListAgentGroups = (
  searchQuery: string,
  newChatDesign: boolean
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

  const groups = useMemo<AgentThreadGroup[] | null>(() => {
    const itemsById = new Map(
      (
        threadItems as ReadonlyArray<{
          id: string;
          title?: string;
          remoteId?: string;
          custom?: { lastMessageAt?: string; agentId?: number };
        }>
      ).map((item) => [item.id, item])
    );
    const dates: (Date | undefined)[] = threadIds.map((id) => {
      const raw = itemsById.get(id)?.custom?.lastMessageAt;
      return raw ? new Date(raw) : undefined;
    });
    if (!dates.some(Boolean)) return null;

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
      .sort((a, b) => time(b) - time(a));

    const query = searchQuery.trim().toLowerCase();
    const groups: AgentThreadGroup[] = [];
    const groupByAgent = new Map<number | null, AgentThreadGroup>();
    for (const index of indices) {
      const item = itemsById.get(threadIds[index]);
      const agentId =
        typeof item?.custom?.agentId === "number"
          ? item.custom.agentId
          : (threadAgentOverrides[threadIds[index]] ?? null);
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
        const threadTitle = item?.title?.toLowerCase() ?? "";
        if (!agentNameMatch && !threadTitle.includes(query)) {
          continue;
        }
      }
      group.entries.push({
        id: threadIds[index],
        index,
        hasRemoteId: Boolean(itemsById.get(threadIds[index])?.remoteId),
      });
    }
    if (query) {
      return groups.filter((group) => group.entries.length > 0);
    }
    return groups;
  }, [
    threadIds,
    threadItems,
    availableMainAgents,
    t,
    searchQuery,
    newChatDesign,
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
  searchQuery: string
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
      if (!query) return null;
      return [
        {
          label: "chat.threadList.recentConversations",
          entries: threadIds
            .map((id, index) => ({ id, index }))
            .filter((_, index) => matches[index]),
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
      .filter((_, index) => matches[index])
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
  }, [threadIds, threadItems, generatedTitles, searchQuery, pinnedIds]);
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
> = ({ completedConversations, generatedTitles, variant = "agent" }) => {
  return (
    <ThreadListItemPrimitive.Root
      className={
        variant === "time"
          ? "group/item flex h-10 items-center gap-2 rounded-lg px-2 py-2 hover:bg-white data-[active=true]:bg-white"
          : "group/item flex h-10 items-center rounded-lg hover:bg-white/70 data-[active=true]:bg-white"
      }
    >
      <ThreadListItemContent
        completedConversations={completedConversations}
        generatedTitles={generatedTitles}
        variant={variant}
      />
    </ThreadListItemPrimitive.Root>
  );
};

interface ThreadListItemContentProps {
  completedConversations: Set<string>;
  generatedTitles?: ReadonlyMap<string, string>;
  variant?: "agent" | "time";
}

const ThreadListItemContent: FC<ThreadListItemContentProps> = ({
  completedConversations,
  generatedTitles,
  variant = "agent",
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
  const threadListItem = aui.threadListItem;
  const title =
    generatedTitles?.get(thread.id) ?? thread.title ?? t("chat.thread.newChat");

  const pinned = usePinnedThreads();
  const isPinned = pinned?.pinnedIds.has(thread.id) ?? false;

  const handleRename = async (newTitle: string) => {
    const normalized = newTitle.trim();
    if (!normalized) return;
    setPendingThreadOperationId(thread.id);
    try {
      await threadListItem.rename(normalized);
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
          {variant === "time" ? (
            <ThreadRowEndStatus />
          ) : (
            <ConversationStatusIndicatorWrapper
              completedConversations={completedConversations}
            />
          )}
        </div>
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
      </ThreadListItemPrimitive.Trigger>
    );
  };

  return (
    <>
      {renderMainContent()}
      {!isEditing && !batchMode && (
        <ThreadListItemMorePrimitive.Root>
          <ThreadListItemMorePrimitive.Trigger className="size-7 shrink-0 rounded-md opacity-0 group-hover/item:opacity-100">
            <MoreHorizontalIcon className="size-4" />
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
  const status = aui.threadListItem().getState().status as string;
  const isRunning = status === "running" || status === "streaming";

  return (
    <ConversationStatusIndicator isStreaming={isRunning} isCompleted={false} />
  );
};

// End-of-row status icon for the workbench time-group list: running shows an
// inline spinner; an error status (when surfaced) shows an orange alert.
const ThreadRowEndStatus: FC = () => {
  const aui = useAui();
  const status = aui.threadListItem().getState().status as string;
  const isRunning = status === "running" || status === "streaming";
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
