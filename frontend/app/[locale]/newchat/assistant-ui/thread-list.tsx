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
  MoreHorizontalIcon,
  PencilIcon,
  TrashIcon,
  Clock,
  ArrowDownIcon,
  CheckIcon,
  XIcon,
  Repeat2Icon,
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
import log from "@/lib/logger";
import { conversationService } from "@/services/conversationService";
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

export const BatchSidebarFooter: FC<{ onSwitchToLegacy: () => void }> = ({
  onSwitchToLegacy,
}) => {
  const { t } = useTranslation();
  const {
    batchMode,
    selectedIds,
    enter,
    exit,
    selectAllVisible,
    deleteSelected,
  } = useBatchSelection()!;

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

  return (
    <div className="flex flex-col gap-1.5">
      <button
        type="button"
        className="flex h-9 w-full items-center justify-center gap-2 rounded-lg border px-3 text-sm hover:bg-muted bg-white"
        onClick={enter}
      >
        <CheckIcon className="size-4 shrink-0" />
        <span>{t("chat.threadList.batchManage")}</span>
      </button>
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

interface ThreadListProps {
  generatedTitles?: ReadonlyMap<string, string>;
}

export const ThreadList: FC<ThreadListProps> = ({
  generatedTitles,
}) => {
  const { t } = useTranslation();
  const completedConversations = useMemo(() => new Set<string>(), []);
  const isLoading = useAuiState((s) => s.threads.isLoading);
  const isLoadingMore = useAuiState((s) => s.threads.isLoadingMore);
  const hasMore = useAuiState((s) => s.threads.hasMore);

  return (
    <div className="flex flex-col p-2">
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
        />
      </AuiIf>
      <ThreadListPrimitive.LoadMore
        disabled={!hasMore || isLoading || isLoadingMore}
        className="mt-1 flex h-8 w-full items-center justify-center gap-2 rounded-lg px-3 text-xs text-muted-foreground hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
      >
        {hasMore ? <ArrowDownIcon className="size-3.5" /> : null}
        <span>
          {isLoading || isLoadingMore
            ? t("chat.threadList.loadingMore")
            : hasMore
              ? t("chat.threadList.loadMore")
              : t("chat.threadList.allLoaded")}
        </span>
      </ThreadListPrimitive.LoadMore>
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
}

const ThreadListItems: FC<ThreadListItemsProps> = ({
  completedConversations,
  generatedTitles,
}) => {
  const { t } = useTranslation();

  const groups = useThreadListGroups();

  const GroupedThreadListItem = useMemo<FC>(
    () => () => (
      <ThreadListItem
        completedConversations={completedConversations}
        generatedTitles={generatedTitles}
      />
    ),
    [completedConversations, generatedTitles]
  );

  if (!groups) {
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

  // Render each thread by index so we can interleave group labels between
  // recency buckets without giving up the runtime's per-item context.
  return (
    <div className="flex flex-col">
      {groups.map((group) => (
        <Fragment key={group.label}>
          <div
            data-slot="aui_thread-list-group-label"
            className="px-3 pt-3 pb-1 text-xs font-medium text-[#4379EE]"
          >
            {t(group.label)}
          </div>
          {group.entries.map(({ id, index }) => (
            <ThreadListPrimitive.ItemByIndex
              key={id}
              index={index}
              components={{ ThreadListItem: GroupedThreadListItem }}
            />
          ))}
        </Fragment>
      ))}
    </div>
  );
};

const DAY_IN_MS = 86_400_000;

type ThreadListGroupEntry = { id: string; index: number };

type ThreadListGroup = {
  label: string;
  entries: ThreadListGroupEntry[];
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

// Build ordered recency groups for the current thread list. Returns null when
// no thread has a usable timestamp so the caller can render a flat list.
const useThreadListGroups = (): ThreadListGroup[] | null => {
  const threadIds = useAuiState((s) => s.threads.threadIds);
  const threadItems = useAuiState((s) => s.threads.threadItems);

  return useMemo<ThreadListGroup[] | null>(() => {
    const itemsById = new Map(
      (
        threadItems as ReadonlyArray<{
          id: string;
          custom?: { lastMessageAt?: string };
        }>
      ).map((item) => [item.id, item])
    );
    const dates: (Date | undefined)[] = threadIds.map((id) => {
      const raw = itemsById.get(id)?.custom?.lastMessageAt;
      return raw ? new Date(raw) : undefined;
    });
    if (!dates.some(Boolean)) return null;

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
      .sort((a, b) => time(b) - time(a));

    const result: ThreadListGroup[] = [];
    for (const index of indices) {
      const label = dateGroupLabel(dates[index], startOfToday);
      const entry: ThreadListGroupEntry = { id: threadIds[index], index };
      const lastGroup = result[result.length - 1];
      if (lastGroup?.label === label) {
        lastGroup.entries.push(entry);
      } else {
        result.push({ label, entries: [entry] });
      }
    }
    return result;
  }, [threadIds, threadItems]);
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

const ThreadListItem: FC<ThreadListItemProps> = ({
  completedConversations,
  generatedTitles,
}) => {
  return (
    <ThreadListItemPrimitive.Root className="group/item flex h-9 items-center rounded-lg hover:bg-muted data-[active=true]:bg-muted">
      <ThreadListItemContent
        completedConversations={completedConversations}
        generatedTitles={generatedTitles}
      />
    </ThreadListItemPrimitive.Root>
  );
};

interface ThreadListItemContentProps {
  completedConversations: Set<string>;
  generatedTitles?: ReadonlyMap<string, string>;
}

const ThreadListItemContent: FC<ThreadListItemContentProps> = ({
  completedConversations,
  generatedTitles,
}) => {
  const aui = useAui();
  const { t } = useTranslation();
  const { confirm } = useConfirmModal();
  const [isEditing, setIsEditing] = useState(false);
  const batch = useBatchSelection();
  const batchMode = batch?.batchMode ?? false;
  const selectedIds = batch?.selectedIds;
  const toggle = batch?.toggle;
  const threadListItem = aui.threadListItem;
  const thread = threadListItem.getState();
  const title =
    generatedTitles?.get(thread.id) ?? thread.title ?? t("chat.thread.newChat");

  const handleRename = useCallback(
    async (newTitle: string) => {
      setPendingThreadOperationId(thread.id);
      try {
        await threadListItem.rename(newTitle);
        log.log(`[ThreadList] Renamed thread to "${newTitle}"`);
        setIsEditing(false);
      } catch (error) {
        log.error("[ThreadList] Failed to rename thread:", error);
        message.error(t("chat.threadList.renameFailed"));
      } finally {
        setPendingThreadOperationId(undefined);
      }
    },
    [thread.id, threadListItem, t]
  );

  const handleRenameClick = useCallback(() => {
    setIsEditing(true);
  }, []);

  const handleCancelRename = useCallback(() => {
    setIsEditing(false);
  }, []);

  const handleDelete = useCallback(() => {
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
  }, [aui, confirm, t, threadListItem]);

  const renderMainContent = () => {
    if (isEditing) {
      return (
        <InlineRenameEditor
          currentTitle={title}
          onRename={handleRename}
          onCancel={handleCancelRename}
        />
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
      <ThreadListItemPrimitive.Trigger className="flex min-w-0 flex-1 justify-start px-3 text-left text-sm">
        <div className="flex min-w-0 flex-1 items-center text-left">
          <ConversationStatusIndicatorWrapper
            completedConversations={completedConversations}
          />
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="min-w-0 flex-1 truncate text-left">
                {title}
              </span>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-80 break-words">
              {title}
            </TooltipContent>
          </Tooltip>
        </div>
      </ThreadListItemPrimitive.Trigger>
    );
  };

  return (
    <>
      {renderMainContent()}
      {!isEditing && !batchMode && (
        <ThreadListItemMorePrimitive.Root>
          <ThreadListItemMorePrimitive.Trigger className="mr-2 size-7 rounded-md opacity-0 group-hover/item:opacity-100">
            <MoreHorizontalIcon className="size-4" />
          </ThreadListItemMorePrimitive.Trigger>
          <ThreadListItemMorePrimitive.Content className="z-50 rounded-md border bg-popover p-1 shadow-md">
            <ThreadListItemMorePrimitive.Item
              onSelect={() => {
                handleRenameClick();
              }}
              className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
            >
              <PencilIcon className="size-4" />
              {t("chat.threadList.rename")}
            </ThreadListItemMorePrimitive.Item>
            <ThreadListItemMorePrimitive.Item
              onSelect={() => {
                setTimeout(handleDelete, 0);
              }}
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
  const status = aui.threadListItem.getState().status as string;
  const isRunning = status === "running" || status === "streaming";

  return (
    <ConversationStatusIndicator isStreaming={isRunning} isCompleted={false} />
  );
};

// Inline rename editor component
const InlineRenameEditor: FC<{
  currentTitle: string;
  onRename: (newTitle: string) => void;
  onCancel: () => void;
}> = ({ currentTitle, onRename, onCancel }) => {
  const [title, setTitle] = useState(currentTitle);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (title.trim() && title.trim() !== currentTitle) {
        onRename(title.trim());
      } else {
        onCancel();
      }
    },
    [title, currentTitle, onRename, onCancel]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        onCancel();
      }
    },
    [onCancel]
  );

  return (
    <form
      onSubmit={handleSubmit}
      className="flex min-w-0 flex-1 items-center gap-1 px-3 overflow-hidden"
    >
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          if (title.trim() && title.trim() !== currentTitle) {
            onRename(title.trim());
          } else {
            onCancel();
          }
        }}
        autoFocus
        className="shrink min-w-0 flex-1 rounded border border-input px-2 py-1 text-sm outline-none focus:border-ring"
      />
      <div className="flex shrink-0 gap-1">
        <button type="submit" className="p-1 hover:bg-accent rounded">
          <CheckIcon className="size-4" />
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="p-1 hover:bg-accent rounded"
        >
          <XIcon className="size-4" />
        </button>
      </div>
    </form>
  );
};
