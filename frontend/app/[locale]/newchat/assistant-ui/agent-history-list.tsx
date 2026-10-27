// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Checkbox, Dropdown, message } from "antd";
import type { MenuProps } from "antd";
import {
  ChevronRight,
  CircleAlertIcon,
  LayoutGrid,
  LoaderCircle,
  MoreHorizontalIcon,
  PencilIcon,
  PinIcon,
  PinOffIcon,
  TrashIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAui, useAuiEvent, useAuiState } from "@assistant-ui/react";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { conversationService } from "@/services/conversationService";
import type {
  AgentConversationGroup,
  ConversationListItem,
} from "@/types/conversation";
import { cn } from "@/lib/utils";
import log from "@/lib/logger";
import agentChatStyles from "../agent-chat.module.css";
import { usePinnedThreads } from "./thread-pins";
import {
  resolveThreadAgentId,
  useThreadAgentOverrides,
} from "../adapter/thread-agent-registry";

type BatchGroupSelection = {
  selectedCount: number;
  totalCount: number;
  checked: boolean;
  indeterminate: boolean;
  loading: boolean;
  complete: boolean;
};

export interface AgentHistoryBatchControls {
  batchMode: boolean;
  toggle: (id: string) => void;
  isSelected: (id: string) => boolean;
  toggleAgentGroup: (
    agentId: number,
    visibleConversationIds: readonly string[]
  ) => Promise<void>;
  getAgentGroupSelection: (
    agentId: number,
    visibleConversationIds: readonly string[]
  ) => BatchGroupSelection;
  setVisibleConversationIds: (ids?: readonly string[]) => void;
}

type AgentHistoryItem = ConversationListItem & {
  pinned_at?: string | null;
};

type ThreadListItemData = {
  id: string;
  remoteId?: string;
  title?: string;
  custom?: { agentId?: number | string; lastMessageAt?: string | number };
};

export interface AgentHistoryListProps {
  searchQuery: string;
  selectedAgentId?: number;
  generatedTitles?: ReadonlyMap<string, string>;
  onHistoryAgentSelected?: (agentId: number) => void;
  onRenameSuccess?: (
    threadId: string,
    remoteId: string | undefined,
    title: string
  ) => void;
  onNewConversation?: () => void | Promise<void>;
  batch?: AgentHistoryBatchControls | null;
}

const GROUP_PAGE_SIZE = 10;
const CONVERSATION_PAGE_SIZE = 10;
const END_OF_HISTORY_MESSAGE_DURATION_MS = 1200;
const EMPTY_GROUP_KEYS: ReadonlySet<string> = new Set();

const toGroupKey = (agentId: number | null): string =>
  agentId === null ? "other" : `agent:${agentId}`;

const toConversationId = (value: unknown): string | undefined => {
  const numeric = Number(value);
  return Number.isSafeInteger(numeric) && numeric > 0
    ? String(numeric)
    : undefined;
};

const toTimestamp = (
  value: string | number | undefined
): number | undefined => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return undefined;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : undefined;
};

const relativeTime = (
  timestamp: number | undefined,
  t: (key: string, options?: Record<string, unknown>) => string
): string => {
  if (timestamp === undefined || timestamp <= 0) return "";
  const elapsed = Date.now() - timestamp;
  if (elapsed < 0) return "";
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return t("chat.threadList.justNow");
  if (minutes < 60) return t("chat.threadList.minutesAgo", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("chat.threadList.hoursAgo", { count: hours });
  return t("chat.threadList.daysAgo", { count: Math.floor(hours / 24) });
};

export function AgentHistoryViewport({
  children,
  enabled = true,
}: {
  children: ReactNode;
  enabled?: boolean;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [shadows, setShadows] = useState({ top: false, bottom: false });
  const measure = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const overflow =
      viewport.clientHeight > 0 &&
      viewport.scrollHeight > viewport.clientHeight + 1;
    const top = overflow && viewport.scrollTop > 2;
    const bottom =
      overflow &&
      viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop > 2;
    setShadows((previous) =>
      previous.top === top && previous.bottom === bottom
        ? previous
        : { top, bottom }
    );
  }, []);
  useEffect(() => {
    if (!enabled) return;
    const frame = requestAnimationFrame(measure);
    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(measure);
    if (viewportRef.current) observer?.observe(viewportRef.current);
    if (contentRef.current) observer?.observe(contentRef.current);
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
    };
  }, [enabled, measure]);
  if (!enabled) return <>{children}</>;
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={viewportRef}
        data-agent-history-group-viewport
        data-testid="agent-history-group-viewport"
        onScroll={measure}
        className={cn(
          "min-h-0 flex-1 overflow-y-auto overscroll-contain",
          agentChatStyles.scrollArea,
          agentChatStyles.groupViewport
        )}
      >
        <div ref={contentRef}>{children}</div>
      </div>
      {shadows.top && (
        <div
          aria-hidden
          data-testid="agent-history-group-shadow-top"
          className="pointer-events-none absolute inset-x-0 top-0 z-10 h-5 bg-gradient-to-b from-[#f0f0f0] via-[#f0f0f0]/70 to-transparent dark:from-[#191919] dark:via-[#191919]/70"
        />
      )}
      {shadows.bottom && (
        <div
          aria-hidden
          data-testid="agent-history-group-shadow-bottom"
          className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-5 bg-gradient-to-t from-[#f0f0f0] via-[#f0f0f0]/70 to-transparent dark:from-[#191919] dark:via-[#191919]/70"
        />
      )}
    </div>
  );
}

export function AgentHistoryList({
  searchQuery,
  selectedAgentId,
  generatedTitles,
  onHistoryAgentSelected,
  onRenameSuccess,
  onNewConversation,
  batch,
}: AgentHistoryListProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const pinned = usePinnedThreads();
  const threadItems = useAuiState(
    (state) => state.threads.threadItems
  ) as readonly ThreadListItemData[];
  const mainThreadId = useAuiState((state) => state.threads.mainThreadId);
  const threadAgentOverrides = useThreadAgentOverrides();
  const normalizedSearch = searchQuery.trim();
  const activeThread = threadItems.find((item) => item.id === mainThreadId);
  const activeThreadRunning = useAuiState((state) => state.thread.isRunning);
  const activeConversationId = toConversationId(activeThread?.remoteId);
  const activeAgentId = activeThread
    ? resolveThreadAgentId(
        activeThread.custom?.agentId,
        threadAgentOverrides[activeThread.id]
      )
    : null;
  const activeTime = toTimestamp(activeThread?.custom?.lastMessageAt);
  const activeItem = useMemo<AgentHistoryItem | undefined>(() => {
    if (!activeConversationId || !activeThread) return undefined;
    return {
      conversation_id: Number(activeConversationId),
      conversation_title:
        generatedTitles?.get(activeThread.id) ??
        generatedTitles?.get(activeConversationId) ??
        activeThread.title ??
        t("chat.thread.newChat"),
      agent_id: activeAgentId,
      create_time: activeTime ?? 0,
      update_time: activeTime ?? 0,
      last_activity_time: activeTime ?? 0,
    };
  }, [
    activeAgentId,
    activeConversationId,
    activeTime,
    activeThread,
    generatedTitles,
    t,
  ]);

  const groupsQuery = useInfiniteQuery({
    queryKey: ["agentConversationGroups", normalizedSearch],
    queryFn: ({ pageParam }) =>
      conversationService.getAgentGroups({
        limit: GROUP_PAGE_SIZE,
        cursor: pageParam,
        search: normalizedSearch,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page, pages) => {
      if (!page.next_cursor || page.items.length === 0) return undefined;
      return pages
        .slice(0, -1)
        .some((previous) => previous.next_cursor === page.next_cursor)
        ? undefined
        : page.next_cursor;
    },
    enabled: selectedAgentId === undefined,
    retry: false,
    staleTime: 15_000,
  });
  const activeGroupQuery = useQuery({
    queryKey: [
      "activeAgentConversationGroup",
      normalizedSearch,
      activeConversationId ? activeAgentId : null,
    ],
    queryFn: () =>
      conversationService.getAgentGroups({
        limit: 1,
        search: normalizedSearch,
        includeAgentIds:
          activeConversationId && activeAgentId !== null ? [activeAgentId] : [],
        includeOther: Boolean(activeConversationId) && activeAgentId === null,
      }),
    enabled: selectedAgentId === undefined && Boolean(activeConversationId),
    staleTime: 15_000,
  });

  useAuiEvent({ scope: "*", event: "thread.runEnd" }, () => {
    void queryClient.invalidateQueries({
      queryKey: ["agentConversationGroups"],
    });
    void queryClient.invalidateQueries({
      queryKey: ["activeAgentConversationGroup"],
    });
    void queryClient.invalidateQueries({
      queryKey: ["agentConversationGroupConversations"],
    });
    void queryClient.invalidateQueries({
      queryKey: ["conversationAgentHistory"],
    });
  });

  const groups = useMemo(() => {
    if (selectedAgentId !== undefined) {
      return [
        {
          group_key: toGroupKey(selectedAgentId),
          agent_id: selectedAgentId,
          agent_name: null,
          agent_available: true,
          last_activity_time: 0,
          matched_conversation: false,
        } satisfies AgentConversationGroup,
      ];
    }
    const byKey = new Map<string, AgentConversationGroup>();
    const pages = groupsQuery.data?.pages ?? [];
    const activeGroups = activeGroupQuery.data?.included_items ?? [];
    // Keep cursor pages as stable blocks so newly fetched pages do not move
    // pinned or active groups that were already visible.
    for (const [pageIndex, page] of pages.entries()) {
      const groupsForPage = new Map<string, AgentConversationGroup>();
      for (const group of [
        ...page.items,
        ...page.pinned_items,
        ...page.included_items,
        ...(pageIndex === 0 ? activeGroups : []),
      ]) {
        if (!groupsForPage.has(group.group_key)) {
          groupsForPage.set(group.group_key, group);
        }
      }
      const orderedPageGroups = [...groupsForPage.values()].sort(
        (left, right) =>
          right.last_activity_time - left.last_activity_time ||
          (right.agent_id ?? -1) - (left.agent_id ?? -1)
      );
      for (const group of orderedPageGroups) {
        if (!byKey.has(group.group_key)) byKey.set(group.group_key, group);
      }
    }
    for (const group of activeGroups) {
      if (!byKey.has(group.group_key)) byKey.set(group.group_key, group);
    }
    const pinnedGroupOrder = new Map<string, number>();
    for (const item of pinned?.serverPins ?? []) {
      const groupKey = toGroupKey(item.agent_id ?? null);
      if (!pinnedGroupOrder.has(groupKey)) {
        pinnedGroupOrder.set(groupKey, pinnedGroupOrder.size);
      }
    }
    for (const page of pages) {
      for (const group of page.pinned_items) {
        if (!pinnedGroupOrder.has(group.group_key)) {
          pinnedGroupOrder.set(group.group_key, pinnedGroupOrder.size);
        }
      }
    }

    return [...byKey.values()].sort((left, right) => {
      const leftPinOrder = pinnedGroupOrder.get(left.group_key);
      const rightPinOrder = pinnedGroupOrder.get(right.group_key);
      if (leftPinOrder !== undefined && rightPinOrder !== undefined) {
        return leftPinOrder - rightPinOrder;
      }
      if (leftPinOrder !== undefined) return -1;
      if (rightPinOrder !== undefined) return 1;
      return 0;
    });
  }, [
    activeGroupQuery.data,
    groupsQuery.data,
    pinned?.serverPins,
    selectedAgentId,
  ]);

  const [expandedGroupOverrides, setExpandedGroupOverrides] = useState<
    ReadonlyMap<string, boolean>
  >(() => new Map());
  const [searchExpansion, setSearchExpansion] = useState<{
    query: string;
    collapsed: ReadonlySet<string>;
  }>(() => ({ query: normalizedSearch, collapsed: EMPTY_GROUP_KEYS }));
  if (searchExpansion.query !== normalizedSearch) {
    setSearchExpansion({
      query: normalizedSearch,
      collapsed: EMPTY_GROUP_KEYS,
    });
  }
  const collapsedSearchGroups =
    searchExpansion.query === normalizedSearch
      ? searchExpansion.collapsed
      : EMPTY_GROUP_KEYS;
  const [visibleIdsByGroup, setVisibleIdsByGroup] = useState<
    ReadonlyMap<string, readonly string[]>
  >(() => new Map());
  const listRef = useRef<HTMLDivElement | null>(null);
  const groupRequestRef = useRef(false);
  const failedGroupSearchRef = useRef<string | null>(null);
  const groupEndTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined
  );
  const groupEndShownRef = useRef<string | null>(null);
  const [groupEndSearch, setGroupEndSearch] = useState<string | null>(null);
  const showGroupEnd = useCallback((search: string) => {
    if (groupEndShownRef.current === search) return;
    groupEndShownRef.current = search;
    setGroupEndSearch(search);
    if (groupEndTimerRef.current) clearTimeout(groupEndTimerRef.current);
    groupEndTimerRef.current = setTimeout(
      () => setGroupEndSearch(null),
      END_OF_HISTORY_MESSAGE_DURATION_MS
    );
  }, []);
  useEffect(
    () => () => {
      if (groupEndTimerRef.current) clearTimeout(groupEndTimerRef.current);
    },
    []
  );
  const fetchNextGroupPage = groupsQuery.fetchNextPage;
  const loadMoreGroups = useCallback(
    (search: string, announceEnd: boolean, retry = false) => {
      if (
        !groupsQuery.hasNextPage ||
        groupsQuery.isFetching ||
        activeGroupQuery.isFetching ||
        (failedGroupSearchRef.current === search && !retry) ||
        (groupsQuery.isFetchNextPageError && !retry) ||
        groupRequestRef.current
      )
        return;
      groupRequestRef.current = true;
      if (retry) failedGroupSearchRef.current = null;
      void fetchNextGroupPage()
        .then((result) => {
          if (result.isError) failedGroupSearchRef.current = search;
          if (announceEnd && !result.hasNextPage && !result.isError)
            showGroupEnd(search);
        })
        .catch((error: unknown) => {
          failedGroupSearchRef.current = search;
          log.error(
            "[AgentHistoryList] Failed to load the next Agent group page:",
            error
          );
        })
        .finally(() => {
          groupRequestRef.current = false;
        });
    },
    [
      groupsQuery.hasNextPage,
      groupsQuery.isFetching,
      groupsQuery.isFetchNextPageError,
      activeGroupQuery.isFetching,
      fetchNextGroupPage,
      showGroupEnd,
    ]
  );
  useEffect(() => {
    if (selectedAgentId !== undefined) return;
    const list = listRef.current;
    const viewport = list?.closest<HTMLElement>(
      "[data-agent-history-group-viewport]"
    );
    if (!list || !viewport) return;
    const checkPosition = (fromScroll: boolean) => {
      if (viewport.clientHeight <= 0) return;
      const remaining =
        viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop;
      if (remaining > 160) groupEndShownRef.current = null;
      if (remaining > 80) return;
      if (groupsQuery.hasNextPage) loadMoreGroups(normalizedSearch, fromScroll);
      else if (
        fromScroll &&
        !groupsQuery.isFetching &&
        !groupsQuery.isError &&
        viewport.scrollHeight > viewport.clientHeight + 1 &&
        groups.length > 0
      )
        showGroupEnd(normalizedSearch);
    };
    const onScroll = (event: Event) => {
      if (event.target === viewport) checkPosition(true);
    };
    viewport.addEventListener("scroll", onScroll, { passive: true });
    const frame = requestAnimationFrame(() => checkPosition(false));
    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(() => checkPosition(false));
    observer?.observe(viewport);
    observer?.observe(list);
    return () => {
      viewport.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
      observer?.disconnect();
    };
  }, [
    selectedAgentId,
    groups.length,
    groupsQuery.hasNextPage,
    groupsQuery.isFetching,
    groupsQuery.isError,
    loadMoreGroups,
    normalizedSearch,
    showGroupEnd,
  ]);

  const updateGroupVisibleIds = useCallback(
    (groupKey: string, ids: readonly string[]) => {
      setVisibleIdsByGroup((previous) => {
        const current = previous.get(groupKey) ?? [];
        if (
          current.length === ids.length &&
          current.every((id, index) => id === ids[index])
        ) {
          return previous;
        }
        const next = new Map(previous);
        if (ids.length) next.set(groupKey, ids);
        else next.delete(groupKey);
        return next;
      });
    },
    []
  );
  const setVisibleConversationIds = batch?.setVisibleConversationIds;
  useEffect(() => {
    if (!setVisibleConversationIds) return;
    setVisibleConversationIds(
      [...visibleIdsByGroup.values()].flatMap((ids) => [...ids])
    );
    return () => setVisibleConversationIds();
  }, [setVisibleConversationIds, visibleIdsByGroup]);

  const pinSnapshot =
    pinned?.serverPins === undefined
      ? undefined
      : JSON.stringify(pinned.serverPins);
  const previousPinSnapshotRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (pinSnapshot === undefined) return;
    const previous = previousPinSnapshotRef.current;
    previousPinSnapshotRef.current = pinSnapshot;
    if (previous === undefined || previous === pinSnapshot) return;
    void queryClient.invalidateQueries({
      queryKey: ["agentConversationGroups"],
    });
    void queryClient.invalidateQueries({
      queryKey: ["agentConversationGroupConversations"],
    });
  }, [pinSnapshot, queryClient]);

  const lastActivityRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!activeConversationId) return;
    const activityKey = `${activeConversationId}:${activeTime ?? ""}`;
    if (lastActivityRef.current === undefined) {
      lastActivityRef.current = activityKey;
      return;
    }
    if (lastActivityRef.current === activityKey) return;
    lastActivityRef.current = activityKey;
    void queryClient.invalidateQueries({
      queryKey: ["agentConversationGroups"],
    });
    void queryClient.invalidateQueries({
      queryKey: ["agentConversationGroupConversations"],
    });
  }, [activeConversationId, activeTime, queryClient]);

  const toggleGroup = (group: AgentConversationGroup) => {
    if (normalizedSearch && group.matched_conversation) {
      setSearchExpansion((previous) => {
        const collapsed = new Set(
          previous.query === normalizedSearch
            ? previous.collapsed
            : EMPTY_GROUP_KEYS
        );
        if (collapsed.has(group.group_key)) collapsed.delete(group.group_key);
        else collapsed.add(group.group_key);
        return { query: normalizedSearch, collapsed };
      });
      return;
    }
    const activeGroup =
      Boolean(activeConversationId) &&
      toGroupKey(activeAgentId) === group.group_key;
    const isCurrentlyExpanded =
      expandedGroupOverrides.get(group.group_key) ?? activeGroup;
    setExpandedGroupOverrides((previous) => {
      const next = new Map(previous);
      next.set(group.group_key, !isCurrentlyExpanded);
      return next;
    });
  };

  if (
    selectedAgentId === undefined &&
    (groupsQuery.isLoading ||
      (Boolean(activeConversationId) &&
        activeGroupQuery.isLoading &&
        groups.length === 0))
  ) {
    return <AgentHistoryLoading label={t("chat.threadList.loading")} />;
  }
  if (
    selectedAgentId === undefined &&
    groupsQuery.isError &&
    groups.length === 0
  ) {
    return (
      <div className="flex flex-col items-center gap-2 px-3 py-5 text-sm text-muted-foreground">
        <CircleAlertIcon className="size-4" aria-hidden />
        <span>{t("chat.threadList.historyLoadFailed")}</span>
        <button
          type="button"
          className="text-primary hover:underline"
          onClick={() => void groupsQuery.refetch()}
        >
          {t("chat.threadList.retry")}
        </button>
      </div>
    );
  }
  if (groups.length === 0) {
    return (
      <div className="flex items-center px-3 py-4 text-sm text-muted-foreground">
        {normalizedSearch
          ? t("chat.threadList.noSearchResults")
          : t("chat.threadList.noHistory")}
      </div>
    );
  }

  return (
    <div
      ref={listRef}
      className={cn(
        "flex w-full min-w-0 flex-col",
        selectedAgentId !== undefined && "min-h-0 flex-1"
      )}
    >
      {selectedAgentId === undefined &&
        groupsQuery.isError &&
        !groupsQuery.data && (
          <AgentHistoryError
            label={t("chat.threadList.historyLoadFailed")}
            retryLabel={t("chat.threadList.retry")}
            onRetry={() => void groupsQuery.refetch()}
          />
        )}
      {groups.map((group) => {
        const activeBelongsToGroup = Boolean(
          activeConversationId && toGroupKey(activeAgentId) === group.group_key
        );
        const nameMatches = Boolean(
          normalizedSearch &&
          group.agent_name
            ?.toLocaleLowerCase()
            .includes(normalizedSearch.toLocaleLowerCase())
        );
        const expanded =
          selectedAgentId !== undefined ||
          (normalizedSearch && group.matched_conversation
            ? !collapsedSearchGroups.has(group.group_key)
            : (expandedGroupOverrides.get(group.group_key) ??
              activeBelongsToGroup));
        return (
          <AgentHistoryGroupSection
            key={group.group_key}
            group={group}
            expanded={expanded}
            selectedAgent={selectedAgentId !== undefined}
            searchQuery={normalizedSearch}
            groupNameMatches={nameMatches}
            activeItem={activeBelongsToGroup ? activeItem : undefined}
            activeConversationId={
              activeBelongsToGroup ? activeConversationId : undefined
            }
            isActiveRunning={Boolean(
              activeBelongsToGroup && activeThreadRunning
            )}
            generatedTitles={generatedTitles}
            batch={batch}
            onToggleGroup={() => toggleGroup(group)}
            onHistoryAgentSelected={onHistoryAgentSelected}
            onRenameSuccess={onRenameSuccess}
            onNewConversation={onNewConversation}
            onVisibleIdsChange={updateGroupVisibleIds}
          />
        );
      })}
      {selectedAgentId === undefined && groupsQuery.isFetchingNextPage && (
        <div
          role="status"
          aria-label={t("chat.threadList.loadingMore")}
          className="sticky bottom-0 z-10 flex h-8 shrink-0 items-center justify-center bg-[#f0f0f0]/90 dark:bg-[#191919]/90"
        >
          <LoaderCircle
            className="size-4 animate-spin text-muted-foreground"
            aria-hidden
          />
        </div>
      )}
      {selectedAgentId === undefined &&
        groupEndSearch === normalizedSearch &&
        !groupsQuery.hasNextPage &&
        !groupsQuery.isFetching &&
        !groupsQuery.isError && (
          <div
            role="status"
            className="sticky bottom-0 z-10 flex h-8 shrink-0 items-center justify-center bg-[#f0f0f0]/90 text-xs text-muted-foreground dark:bg-[#191919]/90"
          >
            {t("chat.threadList.noMoreAgents")}
          </div>
        )}
      {selectedAgentId === undefined && groupsQuery.isFetchNextPageError && (
        <button
          type="button"
          className="py-2 text-xs text-destructive hover:underline"
          onClick={() => loadMoreGroups(normalizedSearch, true, true)}
        >
          {t("chat.threadList.retry")}
        </button>
      )}
    </div>
  );
}

interface AgentHistoryGroupSectionProps {
  group: AgentConversationGroup;
  expanded: boolean;
  selectedAgent: boolean;
  searchQuery: string;
  groupNameMatches: boolean;
  activeItem?: AgentHistoryItem;
  activeConversationId?: string;
  isActiveRunning: boolean;
  generatedTitles?: ReadonlyMap<string, string>;
  batch?: AgentHistoryBatchControls | null;
  onToggleGroup: () => void;
  onHistoryAgentSelected?: (agentId: number) => void;
  onRenameSuccess?: AgentHistoryListProps["onRenameSuccess"];
  onNewConversation?: AgentHistoryListProps["onNewConversation"];
  onVisibleIdsChange: (groupKey: string, ids: readonly string[]) => void;
}

function AgentHistoryGroupSection({
  group,
  expanded,
  selectedAgent,
  searchQuery,
  groupNameMatches,
  activeItem,
  activeConversationId,
  isActiveRunning,
  generatedTitles,
  batch,
  onToggleGroup,
  onHistoryAgentSelected,
  onRenameSuccess,
  onNewConversation,
  onVisibleIdsChange,
}: AgentHistoryGroupSectionProps) {
  const { t } = useTranslation();
  const aui = useAui();
  const queryClient = useQueryClient();
  const pinned = usePinnedThreads();
  const threadListSearch = groupNameMatches ? "" : searchQuery;
  const pageQuery = useInfiniteQuery({
    queryKey: [
      "agentConversationGroupConversations",
      group.group_key,
      threadListSearch,
    ],
    queryFn: ({ pageParam }) =>
      conversationService.getAgentGroupConversations({
        groupKey: group.group_key,
        limit: CONVERSATION_PAGE_SIZE,
        cursor: pageParam,
        search: threadListSearch,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page, allPages) => {
      const nextCursor = page.next_cursor;
      if (!nextCursor || page.items.length === 0) return undefined;

      const previousPages = allPages.slice(0, -1);
      if (
        previousPages.some(
          (previousPage) => previousPage.next_cursor === nextCursor
        )
      ) {
        return undefined;
      }

      const previousIds = new Set(
        previousPages.flatMap((previousPage) =>
          previousPage.items.map((item) => String(item.conversation_id))
        )
      );
      if (
        page.items.every((item) =>
          previousIds.has(String(item.conversation_id))
        )
      ) {
        return undefined;
      }

      return nextCursor;
    },
    enabled: expanded,
    retry: false,
    staleTime: 15_000,
  });
  const [endMessageSearch, setEndMessageSearch] = useState<string | null>(null);
  const [showDelayedSkeleton, setShowDelayedSkeleton] = useState(false);
  const endMessageTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined
  );
  const endMessageShownSearchRef = useRef<string | null>(null);
  const nextPageRequestRef = useRef(false);
  const scrollLoadArmedRef = useRef(true);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const scrollbarTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined
  );
  const [scrollbarActive, setScrollbarActive] = useState(false);
  const [scrollState, setScrollState] = useState<{
    search: string;
    pageCount: number;
    atTop: boolean;
    atBottom: boolean;
    hasOverflow: boolean;
  } | null>(null);
  const fetchNextPage = pageQuery.fetchNextPage;
  const pageCount = pageQuery.data?.pages.length ?? 0;
  const isAtBottom =
    scrollState?.search === threadListSearch &&
    scrollState.pageCount === pageCount &&
    scrollState.atBottom;
  const isAtTop = scrollState?.search !== threadListSearch || scrollState.atTop;
  const showScrollbarDuringScroll = useCallback(() => {
    setScrollbarActive(true);
    if (scrollbarTimerRef.current) clearTimeout(scrollbarTimerRef.current);
    scrollbarTimerRef.current = setTimeout(() => {
      setScrollbarActive(false);
      scrollbarTimerRef.current = undefined;
    }, 2000);
  }, []);
  useEffect(() => {
    if (!expanded || !pageQuery.isLoading) {
      const timer = setTimeout(() => setShowDelayedSkeleton(false), 0);
      return () => clearTimeout(timer);
    }

    const timer = setTimeout(() => setShowDelayedSkeleton(true), 180);
    return () => clearTimeout(timer);
  }, [expanded, group.group_key, pageQuery.isLoading, threadListSearch]);

  useEffect(
    () => () => {
      if (endMessageTimerRef.current) clearTimeout(endMessageTimerRef.current);
      if (scrollbarTimerRef.current) clearTimeout(scrollbarTimerRef.current);
    },
    []
  );

  const showEndMessageBriefly = useCallback(() => {
    if (endMessageShownSearchRef.current === threadListSearch) return;
    if (endMessageTimerRef.current) clearTimeout(endMessageTimerRef.current);
    endMessageShownSearchRef.current = threadListSearch;
    setEndMessageSearch(threadListSearch);
    const messageSearch = threadListSearch;
    endMessageTimerRef.current = setTimeout(() => {
      setEndMessageSearch((current) =>
        current === messageSearch ? null : current
      );
      endMessageTimerRef.current = undefined;
    }, END_OF_HISTORY_MESSAGE_DURATION_MS);
  }, [threadListSearch]);

  const serverPins = useMemo(
    () =>
      (pinned?.serverPins ?? []).filter((item) =>
        group.agent_id === null
          ? item.agent_id == null
          : item.agent_id === group.agent_id
      ),
    [group.agent_id, pinned?.serverPins]
  );
  const apiRows = useMemo(() => {
    const pages = pageQuery.data?.pages ?? [];
    const ordinary = pages.flatMap((page) => page.items);
    const apiPins = pages.flatMap((page) => page.pinned_items);
    const allPins = [...apiPins, ...serverPins];
    const pinById = new Map<string, AgentHistoryItem>();
    for (const item of allPins) {
      if (searchQuery && !groupNameMatches) {
        if (
          !item.conversation_title
            .toLocaleLowerCase()
            .includes(searchQuery.toLocaleLowerCase())
        ) {
          continue;
        }
      }
      pinById.set(String(item.conversation_id), item);
    }
    const rows = new Map<string, AgentHistoryItem>();
    for (const item of ordinary) rows.set(String(item.conversation_id), item);
    for (const [id, item] of pinById) rows.set(id, item);
    if (
      activeItem &&
      (!searchQuery ||
        groupNameMatches ||
        activeItem.conversation_title
          .toLocaleLowerCase()
          .includes(searchQuery.toLocaleLowerCase()))
    ) {
      const id = String(activeItem.conversation_id);
      const existing = rows.get(id);
      rows.set(id, {
        ...existing,
        ...activeItem,
        create_time: existing?.create_time ?? activeItem.create_time,
        update_time: existing?.update_time ?? activeItem.update_time,
        last_activity_time:
          existing?.last_activity_time ?? activeItem.last_activity_time,
        pinned_at: pinById.get(id)?.pinned_at ?? existing?.pinned_at,
      });
    }
    return [...rows.values()].sort((left, right) => {
      const leftPinned = pinById.has(String(left.conversation_id));
      const rightPinned = pinById.has(String(right.conversation_id));
      if (leftPinned !== rightPinned) return leftPinned ? -1 : 1;
      if (leftPinned && rightPinned) {
        const pinDelta =
          (toTimestamp(right.pinned_at ?? undefined) ?? -1) -
          (toTimestamp(left.pinned_at ?? undefined) ?? -1);
        if (Number.isFinite(pinDelta) && pinDelta !== 0) return pinDelta;
      }
      return (
        (right.last_activity_time ?? right.create_time) -
          (left.last_activity_time ?? left.create_time) ||
        right.conversation_id - left.conversation_id
      );
    });
  }, [activeItem, groupNameMatches, pageQuery.data, searchQuery, serverPins]);

  const visibleRows = useMemo(() => {
    if (expanded) return apiRows;
    return [];
  }, [apiRows, expanded]);
  const showTailStatus =
    pageQuery.isFetchNextPageError ||
    pageQuery.isFetchingNextPage ||
    (endMessageSearch === threadListSearch &&
      !pageQuery.hasNextPage &&
      !pageQuery.isError &&
      !pageQuery.isFetching &&
      visibleRows.length > 0);
  const hasScrollableContent =
    scrollState?.search === threadListSearch &&
    scrollState.pageCount === pageCount
      ? scrollState.hasOverflow
      : visibleRows.length > 8 || pageQuery.hasNextPage;
  const requestNextConversationPage = useCallback(
    (announceEnd: boolean, triggeredByScroll: boolean) => {
      if (
        !pageQuery.hasNextPage ||
        pageQuery.isFetching ||
        pageQuery.isFetchNextPageError ||
        nextPageRequestRef.current
      ) {
        return;
      }
      if (triggeredByScroll) scrollLoadArmedRef.current = false;
      nextPageRequestRef.current = true;
      void fetchNextPage()
        .then((result) => {
          if (
            announceEnd &&
            !result.hasNextPage &&
            !result.isFetchNextPageError
          ) {
            showEndMessageBriefly();
          }
        })
        .catch((error: unknown) => {
          log.error(
            "[AgentHistoryList] Failed to load the next history page:",
            error
          );
        })
        .finally(() => {
          nextPageRequestRef.current = false;
        });
    },
    [
      pageQuery.hasNextPage,
      pageQuery.isFetchNextPageError,
      pageQuery.isFetching,
      fetchNextPage,
      showEndMessageBriefly,
    ]
  );

  const updateViewportMeasurements = useCallback(
    (viewport: HTMLDivElement) => {
      const isMeasured = viewport.clientHeight > 0;
      const distanceToBottom =
        viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
      const hasOverflow = isMeasured
        ? viewport.scrollHeight > viewport.clientHeight + 1
        : visibleRows.length > 8 || pageQuery.hasNextPage;
      const next = {
        search: threadListSearch,
        pageCount,
        atTop: viewport.scrollTop <= 2,
        atBottom: isMeasured ? distanceToBottom <= 2 : !hasOverflow,
        hasOverflow,
      };
      setScrollState((previous) =>
        previous?.search === next.search &&
        previous.pageCount === next.pageCount &&
        previous.atTop === next.atTop &&
        previous.atBottom === next.atBottom &&
        previous.hasOverflow === next.hasOverflow
          ? previous
          : next
      );
      if (isMeasured && !hasOverflow) setScrollbarActive(false);
    },
    [pageCount, pageQuery.hasNextPage, threadListSearch, visibleRows.length]
  );

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const viewport = viewportRef.current;
      if (viewport) updateViewportMeasurements(viewport);
    });
    return () => cancelAnimationFrame(frame);
  }, [expanded, showTailStatus, updateViewportMeasurements]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() =>
      updateViewportMeasurements(viewport)
    );
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [updateViewportMeasurements]);

  useEffect(() => {
    if (
      !selectedAgent ||
      !expanded ||
      !pageQuery.hasNextPage ||
      pageQuery.isLoading ||
      pageQuery.isFetching ||
      pageQuery.isFetchNextPageError ||
      pageQuery.isError
    ) {
      return;
    }

    const frame = requestAnimationFrame(() => {
      const viewport = viewportRef.current;
      if (!viewport || viewport.clientHeight <= 0) return;
      const distanceToBottom =
        viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
      if (distanceToBottom <= 80) {
        requestNextConversationPage(false, false);
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [
    expanded,
    pageCount,
    pageQuery.hasNextPage,
    pageQuery.isError,
    pageQuery.isFetchNextPageError,
    pageQuery.isFetching,
    pageQuery.isLoading,
    requestNextConversationPage,
    selectedAgent,
    visibleRows.length,
  ]);

  const isConversationPinned = (item: AgentHistoryItem): boolean => {
    const id = String(item.conversation_id);
    return (
      (pageQuery.data?.pages ?? []).some((page) =>
        page.pinned_items.some(
          (candidate) => candidate.conversation_id === item.conversation_id
        )
      ) ||
      serverPins.some(
        (candidate) => candidate.conversation_id === item.conversation_id
      ) ||
      (pinned?.isPinned({ id, remoteId: id }) ?? false)
    );
  };

  const showInitialSkeleton =
    expanded &&
    pageQuery.isLoading &&
    showDelayedSkeleton &&
    visibleRows.length === 0;
  const showEmptyHistory =
    selectedAgent &&
    !pageQuery.isLoading &&
    !pageQuery.isError &&
    visibleRows.length === 0;
  const showFirstPageError = pageQuery.isError && !pageQuery.data;
  const hasPinnedRows = visibleRows.some(isConversationPinned);
  const hasRegularRows = visibleRows.some(
    (item) => !isConversationPinned(item)
  );
  const separatorHeight = hasPinnedRows && hasRegularRows ? 17 : 0;
  const contentHeight =
    visibleRows.length * 40 + separatorHeight + (showTailStatus ? 32 : 0);
  const desiredViewportHeight = showInitialSkeleton
    ? 320
    : showFirstPageError
      ? 64
      : showEmptyHistory
        ? 48
        : contentHeight;

  const visibleConversationIds = useMemo(
    () => visibleRows.map((item) => String(item.conversation_id)),
    [visibleRows]
  );

  useEffect(() => {
    onVisibleIdsChange(group.group_key, visibleConversationIds);
  }, [group.group_key, onVisibleIdsChange, visibleConversationIds]);

  useEffect(
    () => () => onVisibleIdsChange(group.group_key, []),
    [group.group_key, onVisibleIdsChange]
  );

  const title =
    group.agent_id === null
      ? t("chat.threadList.recentConversations")
      : group.agent_name ||
        t("chat.threadList.unavailableAgent", { id: group.agent_id });
  const selection =
    batch?.batchMode && group.agent_id !== null
      ? batch.getAgentGroupSelection(
          group.agent_id,
          apiRows.map((item) => String(item.conversation_id))
        )
      : undefined;

  const header = (
    <div className="flex h-10 w-full min-w-0 items-center gap-1 rounded-lg px-1 hover:bg-[#e5e7eb]">
      {selection && (
        <Checkbox
          aria-label={t("chat.threadList.selectAgentConversations", {
            agent: title,
          })}
          checked={selection.checked}
          indeterminate={selection.indeterminate}
          disabled={selection.loading}
          onChange={() =>
            void batch?.toggleAgentGroup(
              group.agent_id as number,
              apiRows.map((item) => String(item.conversation_id))
            )
          }
        />
      )}
      <button
        type="button"
        data-slot="aui_thread-list-group-label"
        className={cn(
          "group flex h-full min-w-0 flex-1 items-center gap-5 rounded-lg px-0 text-left text-[14px] text-[#191919]",
          selectedAgent && "hidden"
        )}
        onClick={onToggleGroup}
        aria-expanded={expanded}
        title={title}
      >
        <LayoutGrid className="size-5 shrink-0 text-[#191919]" aria-hidden />
        <span className="min-w-0 flex-1 truncate">{title}</span>
        {group.agent_id !== null && !group.agent_available && (
          <span className="shrink-0 text-xs text-[#8c8c8c]">
            {t("chat.threadList.agentUnavailable")}
          </span>
        )}
        <ChevronRight
          className={cn(
            "size-3.5 w-0 shrink-0 overflow-hidden text-[#808080] opacity-0 transition-all duration-200 group-hover:w-3.5 group-hover:opacity-100 group-focus-visible:w-3.5 group-focus-visible:opacity-100",
            expanded && "rotate-90"
          )}
          aria-hidden
        />
      </button>
      {selection?.loading ? (
        <LoaderCircle
          aria-hidden
          className="size-3.5 shrink-0 animate-spin text-[#808080]"
        />
      ) : selection?.complete ? (
        <span className="shrink-0 pr-2 text-xs text-[#1677ff]">
          {selection.selectedCount}/{selection.totalCount}
        </span>
      ) : null}
    </div>
  );

  return (
    <div
      className={cn(
        "flex w-full min-w-0 flex-col",
        selectedAgent && "h-full min-h-0 flex-1"
      )}
    >
      {!selectedAgent && header}
      <div
        className={cn("relative mr-[2px]", selectedAgent && "min-h-0 flex-1")}
      >
        <div
          ref={viewportRef}
          data-testid="agent-history-conversation-viewport"
          data-agent-history-scrolling={scrollbarActive ? "true" : undefined}
          role="region"
          aria-label={t("chat.threadList.historyScrollRegion")}
          onScroll={(event) => {
            const viewport = event.currentTarget;
            const distanceToBottom =
              viewport.scrollHeight -
              viewport.scrollTop -
              viewport.clientHeight;
            const nearEnd = distanceToBottom <= 80;
            if (distanceToBottom > 160) {
              scrollLoadArmedRef.current = true;
              endMessageShownSearchRef.current = null;
            }
            updateViewportMeasurements(viewport);
            if (
              viewport.clientHeight > 0 &&
              viewport.scrollHeight > viewport.clientHeight + 1
            ) {
              showScrollbarDuringScroll();
            } else {
              setScrollbarActive(false);
            }
            if (!nearEnd) {
              if (endMessageTimerRef.current) {
                clearTimeout(endMessageTimerRef.current);
                endMessageTimerRef.current = undefined;
              }
              setEndMessageSearch(null);
              return;
            }

            if (pageQuery.hasNextPage) {
              setEndMessageSearch(null);
              endMessageShownSearchRef.current = null;
              if (!scrollLoadArmedRef.current) return;
              if (!pageQuery.isFetchingNextPage) {
                requestNextConversationPage(true, true);
              }
              return;
            }

            if (
              !pageQuery.isFetching &&
              !pageQuery.isError &&
              visibleRows.length > 0
            ) {
              showEndMessageBriefly();
            }
          }}
          className={cn(
            agentChatStyles.scrollArea,
            "overflow-y-auto overscroll-contain",
            selectedAgent ? "h-full min-h-0 flex-1 max-h-none" : "max-h-[320px]"
          )}
          style={{
            width: "100%",
            height: selectedAgent
              ? "100%"
              : expanded
                ? Math.min(desiredViewportHeight, 320)
                : 0,
            transition: "height 180ms ease-out",
          }}
        >
          {showInitialSkeleton ? (
            <ConversationRowsSkeleton label={t("chat.threadList.loading")} />
          ) : (
            visibleRows.map((item, index) => {
              const id = String(item.conversation_id);
              const pinKey = { id, remoteId: id };
              const isPinned = isConversationPinned(item);
              const previousItem = visibleRows[index - 1];
              const startsRegularHistory =
                previousItem && isConversationPinned(previousItem) && !isPinned;
              const active = id === activeConversationId;
              const title =
                generatedTitles?.get(id) ??
                item.conversation_title ??
                t("chat.thread.newChat");
              return (
                <Fragment key={id}>
                  {startsRegularHistory && (
                    <div
                      role="separator"
                      className="mx-3 my-2 border-t border-dashed border-gray-400/60 dark:border-gray-500/70"
                    />
                  )}
                  <AgentHistoryRow
                    item={item}
                    title={title}
                    active={active}
                    running={active && isActiveRunning}
                    pinned={isPinned}
                    pinDisabled={!pinned?.canPin(pinKey)}
                    batch={batch}
                    onSelect={() => aui.threads.switchToThread(id)}
                    onHistoryAgentSelected={onHistoryAgentSelected}
                    onRenameSuccess={onRenameSuccess}
                    onNewConversation={onNewConversation}
                    onInvalidate={() => {
                      void queryClient.invalidateQueries({
                        queryKey: ["agentConversationGroups"],
                      });
                      void queryClient.invalidateQueries({
                        queryKey: ["agentConversationGroupConversations"],
                      });
                      void queryClient.invalidateQueries({
                        queryKey: ["workbench-pins"],
                      });
                    }}
                  />
                </Fragment>
              );
            })
          )}
          {showFirstPageError && (
            <AgentHistoryError
              label={t("chat.threadList.historyLoadFailed")}
              retryLabel={t("chat.threadList.retry")}
              onRetry={() => void pageQuery.refetch()}
            />
          )}
          {showEmptyHistory && (
            <div className="px-3 py-3 text-sm text-muted-foreground">
              {searchQuery
                ? t("chat.threadList.noSearchResults")
                : t("chat.threadList.noHistory")}
            </div>
          )}
          {expanded && pageQuery.isFetchNextPageError && (
            <button
              type="button"
              className="flex h-8 w-full items-center justify-center text-xs text-destructive hover:underline"
              onClick={() => void pageQuery.fetchNextPage()}
            >
              {t("chat.threadList.retry")}
            </button>
          )}
          {expanded && pageQuery.isFetchingNextPage && (
            <div
              role="status"
              aria-label={t("chat.threadList.loadingMore")}
              className="sticky bottom-0 z-10 flex h-8 items-center justify-center bg-[#f0f0f0]/90 dark:bg-[#191919]/90"
            >
              <LoaderCircle
                className="size-4 animate-spin text-muted-foreground"
                aria-hidden
              />
            </div>
          )}
          {expanded &&
            endMessageSearch === threadListSearch &&
            !pageQuery.hasNextPage &&
            !pageQuery.isError &&
            !pageQuery.isFetching &&
            visibleRows.length > 0 && (
              <div
                role="status"
                className="sticky bottom-0 z-10 flex h-8 items-center justify-center bg-[#f0f0f0]/90 text-xs text-muted-foreground dark:bg-[#191919]/90"
              >
                {t("chat.threadList.noMoreConversations")}
              </div>
            )}
        </div>
        {expanded && hasScrollableContent && !isAtTop && (
          <div
            aria-hidden
            data-testid="agent-history-scroll-shadow-top"
            className="pointer-events-none absolute inset-x-0 top-0 z-10 h-5 bg-gradient-to-b from-[#f0f0f0] via-[#f0f0f0]/70 to-transparent dark:from-[#191919] dark:via-[#191919]/70"
          />
        )}
        {expanded && hasScrollableContent && !isAtBottom && (
          <div
            aria-hidden
            data-testid="agent-history-scroll-shadow-bottom"
            className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-5 bg-gradient-to-t from-[#f0f0f0] via-[#f0f0f0]/70 to-transparent dark:from-[#191919] dark:via-[#191919]/70"
          />
        )}
      </div>
    </div>
  );
}

interface AgentHistoryRowProps {
  item: AgentHistoryItem;
  title: string;
  active: boolean;
  running: boolean;
  pinned: boolean;
  pinDisabled: boolean;
  batch?: AgentHistoryBatchControls | null;
  onSelect: () => void | Promise<void>;
  onHistoryAgentSelected?: (agentId: number) => void;
  onRenameSuccess?: AgentHistoryListProps["onRenameSuccess"];
  onNewConversation?: AgentHistoryListProps["onNewConversation"];
  onInvalidate: () => void;
}

function AgentHistoryRow({
  item,
  title,
  active,
  running,
  pinned,
  pinDisabled,
  batch,
  onSelect,
  onHistoryAgentSelected,
  onRenameSuccess,
  onNewConversation,
  onInvalidate,
}: AgentHistoryRowProps) {
  const { t } = useTranslation();
  const aui = useAui();
  const { confirm } = useConfirmModal();
  const pin = usePinnedThreads();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const conversationId = String(item.conversation_id);
  const selected = batch?.isSelected(conversationId) ?? false;
  const timestamp = item.last_activity_time ?? item.create_time;

  const rename = async (value: string) => {
    const normalized = value.trim();
    if (!normalized || normalized === title) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await conversationService.rename(Number(conversationId), normalized);
      onRenameSuccess?.(conversationId, conversationId, normalized);
      onInvalidate();
      setEditing(false);
    } catch (error) {
      log.error("[AgentHistoryList] Failed to rename conversation:", error);
      message.error(t("chat.threadList.renameFailed"));
    } finally {
      setSaving(false);
    }
  };

  const deleteConversation = () => {
    confirm({
      title: t("chat.threadList.delete"),
      content: t("chat.threadList.confirmDeletionDescription"),
      onOk: async () => {
        try {
          await conversationService.delete(Number(conversationId));
          await aui.threads.reload();
          onInvalidate();
          if (active) await onNewConversation?.();
        } catch (error) {
          log.error("[AgentHistoryList] Failed to delete conversation:", error);
          message.error(t("chatInterface.deleteFailed"));
          throw error;
        }
      },
    });
  };

  const menuItems: MenuProps["items"] = [
    {
      key: "pin",
      icon: pinned ? (
        <PinOffIcon className="size-4" />
      ) : (
        <PinIcon className="size-4" />
      ),
      label: pinned ? t("chat.threadList.unpin") : t("chat.threadList.pin"),
      disabled: pinDisabled,
    },
    {
      key: "rename",
      icon: <PencilIcon className="size-4" />,
      label: t("chat.threadList.rename"),
    },
    {
      key: "delete",
      icon: <TrashIcon className="size-4" />,
      label: t("chat.threadList.delete"),
      danger: true,
    },
  ];

  return (
    <div
      data-active={active || undefined}
      data-pinned={pinned || undefined}
      className={cn(
        "group/item flex h-10 w-full min-w-0 items-center rounded-lg hover:bg-[#e5e7eb]",
        active && "bg-[#e5e7eb]"
      )}
    >
      {editing ? (
        <form
          className="flex min-w-0 flex-1 items-center gap-1 px-2"
          onSubmit={(event) => {
            event.preventDefault();
            const value = new FormData(event.currentTarget).get("title");
            if (typeof value === "string") void rename(value);
          }}
        >
          <input
            autoFocus
            name="title"
            defaultValue={title}
            aria-label={t("chat.threadList.rename")}
            className="h-8 min-w-0 flex-1 rounded border bg-background px-2 text-sm"
            onKeyDown={(event) => {
              if (event.key === "Escape") setEditing(false);
            }}
          />
          <button
            type="submit"
            className="text-xs text-primary"
            disabled={saving}
          >
            {t("common.save", { defaultValue: "Save" })}
          </button>
          <button
            type="button"
            className="text-xs text-muted-foreground"
            onClick={() => setEditing(false)}
          >
            {t("common.cancel", { defaultValue: "Cancel" })}
          </button>
        </form>
      ) : (
        <>
          {batch?.batchMode ? (
            <div className="flex h-full min-w-0 flex-1 items-center gap-2 px-2 text-sm">
              <Checkbox
                className="!m-0 shrink-0"
                checked={selected}
                onChange={() => batch.toggle(conversationId)}
              />
              <button
                type="button"
                aria-pressed={selected}
                className={cn(
                  "flex h-full min-w-0 flex-1 items-center gap-2 rounded-lg text-left",
                  selected && "bg-accent"
                )}
                onClick={() => batch.toggle(conversationId)}
                title={title}
              >
                <span className="min-w-0 flex-1 truncate">{title}</span>
                <span className="shrink-0 text-xs text-[#8c8c8c]">
                  {relativeTime(timestamp, t)}
                </span>
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="flex h-full min-w-0 flex-1 items-center gap-2 pl-3 pr-2 text-left text-[14px] text-[#595959] group-hover/item:text-[#191919]"
              onClick={() => {
                void Promise.resolve()
                  .then(onSelect)
                  .then(() => {
                    if (item.agent_id !== null && item.agent_id !== undefined) {
                      onHistoryAgentSelected?.(item.agent_id);
                    }
                  })
                  .catch((error) => {
                    log.error(
                      "[AgentHistoryList] Failed to open conversation:",
                      error
                    );
                    message.error(t("chat.threadList.historyLoadFailed"));
                  });
              }}
              title={title}
            >
              {pinned && (
                <PinIcon
                  className="size-3 shrink-0 text-blue-500"
                  aria-label={t("chat.threadList.pinned")}
                />
              )}
              <span className="min-w-0 flex-1 truncate">{title}</span>
              {running ? (
                <LoaderCircle
                  role="status"
                  aria-label={t("chat.threadList.running")}
                  className="size-3 shrink-0 animate-spin text-[#808080]"
                />
              ) : (
                <span className="shrink-0 text-xs text-[#808080]">
                  {relativeTime(timestamp, t)}
                </span>
              )}
            </button>
          )}
          {!batch?.batchMode && (
            <Dropdown
              trigger={["click"]}
              menu={{
                items: menuItems,
                onClick: ({ key }) => {
                  if (key === "pin") {
                    pin?.togglePin({
                      id: conversationId,
                      remoteId: conversationId,
                    });
                  } else if (key === "rename") {
                    setEditing(true);
                  } else if (key === "delete") {
                    setTimeout(deleteConversation, 0);
                  }
                },
              }}
            >
              <button
                type="button"
                aria-label={t("chat.threadList.moreActions", { title })}
                className="mr-1 size-7 shrink-0 rounded-md opacity-0 group-hover/item:opacity-100 group-focus-within/item:opacity-100 focus-visible:opacity-100"
                onClick={(event) => event.stopPropagation()}
              >
                <MoreHorizontalIcon className="mx-auto size-4" />
              </button>
            </Dropdown>
          )}
        </>
      )}
    </div>
  );
}

function AgentHistoryLoading({ label }: { label: string }) {
  return (
    <div className="space-y-3 px-2 py-3" role="status" aria-label={label}>
      {Array.from({ length: 3 }, (_, groupIndex) => (
        <div key={groupIndex} className="space-y-1.5">
          <div className="flex h-10 items-center gap-3 rounded-lg px-3">
            <div className="size-3 animate-pulse rounded-sm bg-[#d5d9df] motion-reduce:animate-none" />
            <div className="h-3.5 w-2/5 animate-pulse rounded bg-[#d5d9df] motion-reduce:animate-none" />
          </div>
          {groupIndex === 0 &&
            Array.from({ length: 2 }, (_, rowIndex) => (
              <div
                key={rowIndex}
                className="flex h-10 items-center gap-3 rounded-lg px-8"
              >
                <div className="size-4 shrink-0 animate-pulse rounded-full bg-[#e0e3e8] motion-reduce:animate-none" />
                <div
                  className={cn(
                    "h-3 animate-pulse rounded bg-[#e0e3e8] motion-reduce:animate-none",
                    rowIndex === 0 ? "w-3/5" : "w-2/5"
                  )}
                />
              </div>
            ))}
        </div>
      ))}
    </div>
  );
}

function ConversationRowsSkeleton({ label }: { label: string }) {
  return (
    <div className="space-y-1 px-2 py-1" role="status" aria-label={label}>
      {Array.from({ length: 8 }, (_, index) => (
        <div
          key={index}
          className="flex h-10 items-center gap-3 rounded-lg px-8"
        >
          <div className="size-4 shrink-0 animate-pulse rounded-full bg-[#e0e3e8] motion-reduce:animate-none" />
          <div
            className={cn(
              "h-3 animate-pulse rounded bg-[#e0e3e8] motion-reduce:animate-none",
              ["w-3/5", "w-2/5", "w-1/2"][index % 3]
            )}
          />
        </div>
      ))}
    </div>
  );
}

function AgentHistoryError({
  label,
  retryLabel,
  onRetry,
}: {
  label: string;
  retryLabel: string;
  onRetry: () => void;
}) {
  return (
    <div
      className="flex items-center gap-2 px-3 py-2 text-xs text-destructive"
      role="alert"
    >
      <CircleAlertIcon className="size-3.5 shrink-0" aria-hidden />
      <span>{label}</span>
      <button type="button" className="underline" onClick={onRetry}>
        {retryLabel}
      </button>
    </div>
  );
}
