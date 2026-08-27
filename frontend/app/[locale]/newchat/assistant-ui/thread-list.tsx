"use client";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { message } from "antd";
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
  CheckIcon,
  XIcon,
} from "lucide-react";
import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type RefObject,
} from "react";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import { CONVERSATION_PAGE_SIZE } from "@/services/conversationService";
import type { FC } from "react";
import { getConversationPageRequest } from "@/lib/conversationLoadPolicy";
import { runConversationDeletionLifecycle } from "@/lib/conversationThreadPagination";
import {
  calculateConversationVirtualSpacerHeight,
  calculateConversationViewport,
  getConversationViewportGroupCounts,
  isConversationLoadedBoundaryReached,
  newChatConversationViewport,
} from "@/lib/conversationViewport";
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

interface ThreadListProps {
  generatedTitles?: ReadonlyMap<string, string>;
  scrollContainerRef: RefObject<HTMLDivElement>;
}

type DeleteConversation = () => void | Promise<void>;
type DeleteWithPagination = (
  deleteConversation: DeleteConversation
) => Promise<void>;
type RequestConversationPage = (
  isScrollRequest: boolean,
  continueTowardScrollPosition?: boolean
) => void;

const CONVERSATION_LOAD_THRESHOLD = 80;

export const ThreadList: FC<ThreadListProps> = ({
  generatedTitles,
  scrollContainerRef,
}) => {
  const { t } = useTranslation();
  const aui = useAui();
  const hasMore = useAuiState((s) => s.threads.hasMore);
  const isThreadListLoading = useAuiState((s) => s.threads.isLoading);
  const isLoadingMore = useAuiState((s) => s.threads.isLoadingMore);
  const threadCount = useAuiState((s) => s.threads.threadIds.length);
  const conversationMetadata = useSyncExternalStore(
    newChatConversationViewport.subscribe,
    newChatConversationViewport.getSnapshot,
    newChatConversationViewport.getSnapshot
  );
  const loadedItemsRef = useRef<HTMLDivElement>(null);
  const loadMoreSentinelRef = useRef<HTMLDivElement>(null);
  const measurementRowRef = useRef<HTMLDivElement>(null);
  const measurementHeaderRef = useRef<HTMLDivElement>(null);
  const pageLoadPromiseRef = useRef<Promise<void> | null>(null);
  const deletionInFlightRef = useRef(false);
  const requestPageRef = useRef<RequestConversationPage>(() => {});
  const userScrollIntentRef = useRef(false);
  const previousScrollTopRef = useRef(0);
  const [virtualSpacerHeight, setVirtualSpacerHeight] = useState(0);
  const [deletionRevision, setDeletionRevision] = useState(0);

  const getLoadedBoundary = useCallback((): number | null => {
    const container = scrollContainerRef.current;
    const sentinel = loadMoreSentinelRef.current;
    if (!container || !sentinel) return null;

    return (
      sentinel.getBoundingClientRect().top -
      container.getBoundingClientRect().top +
      container.scrollTop +
      sentinel.getBoundingClientRect().height
    );
  }, [scrollContainerRef]);

  const requestPage = useCallback(
    (isScrollRequest: boolean, continueTowardScrollPosition = false) => {
      if (deletionInFlightRef.current || pageLoadPromiseRef.current) return;

      const container = scrollContainerRef.current;
      const measuredRow = measurementRowRef.current;
      const measuredHeader = measurementHeaderRef.current;
      if (!container || !measuredRow || !measuredHeader) return;

      const loadedBoundary = getLoadedBoundary();
      if (
        isScrollRequest &&
        (loadedBoundary === null ||
          !isConversationLoadedBoundaryReached({
            scrollTop: container.scrollTop,
            clientHeight: container.clientHeight,
            loadedBoundary,
            threshold: CONVERSATION_LOAD_THRESHOLD,
          }))
      ) {
        return;
      }

      const rowHeight = measuredRow.getBoundingClientRect().height;
      const viewport = calculateConversationViewport({
        containerHeight: container.clientHeight,
        rowHeight,
        groupHeaderHeight: measuredHeader.getBoundingClientRect().height,
        contentPadding: 16,
        groupCounts: getConversationViewportGroupCounts(conversationMetadata),
      });
      const isLoading = isThreadListLoading || isLoadingMore;
      const request =
        threadCount === 0 && hasMore && !isLoading
          ? {
              limit: viewport.initialLimit,
              reason: "viewport-fill" as const,
            }
          : getConversationPageRequest({
              hasMore,
              isLoading,
              clientHeight: container.clientHeight,
              scrollHeight: loadedBoundary ?? container.scrollHeight,
              rowHeight,
              isLoadRequested: isScrollRequest,
              regularPageSize: CONVERSATION_PAGE_SIZE,
            });
      if (!request) return;

      newChatConversationViewport.requestNextPageSize(request.limit);
      const trackedTask = aui.threads
        .loadMore()
        .then(() => {
          if (continueTowardScrollPosition) {
            requestAnimationFrame(() => requestPageRef.current(true, true));
          }
        })
        .catch((error) =>
          log.error(`Failed to load conversations (${request.reason})`, error)
        )
        .finally(() => {
          newChatConversationViewport.clearNextPageSize();
          if (pageLoadPromiseRef.current === trackedTask) {
            pageLoadPromiseRef.current = null;
          }
        });
      pageLoadPromiseRef.current = trackedTask;
    },
    [
      aui,
      conversationMetadata,
      getLoadedBoundary,
      hasMore,
      isLoadingMore,
      isThreadListLoading,
      scrollContainerRef,
      threadCount,
    ]
  );
  requestPageRef.current = requestPage;

  const deleteWithPagination = useCallback<DeleteWithPagination>(
    async (deleteConversation) => {
      deletionInFlightRef.current = true;

      try {
        await runConversationDeletionLifecycle({
          pendingPageLoad: pageLoadPromiseRef.current,
          deleteConversation,
          recordDeletedLoadedItem: () => {
            newChatConversationViewport.recordDeletedLoadedItem();
            setDeletionRevision((revision) => revision + 1);
          },
        });
      } finally {
        newChatConversationViewport.clearNextPageSize();
        deletionInFlightRef.current = false;
        requestAnimationFrame(() => requestPageRef.current(false));
      }
    },
    []
  );

  useLayoutEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    let frame: number | null = null;

    const measureAndFill = () => {
      frame = null;
      const measuredRow = measurementRowRef.current;
      const measuredHeader = measurementHeaderRef.current;
      const loadedItems = loadedItemsRef.current;
      if (
        measuredRow &&
        measuredHeader &&
        loadedItems &&
        conversationMetadata
      ) {
        const groupCount = getConversationViewportGroupCounts(
          conversationMetadata
        ).filter((count) => count > 0).length;
        const nextSpacerHeight = calculateConversationVirtualSpacerHeight({
          totalCount: conversationMetadata.total,
          pendingDeletionCount:
            newChatConversationViewport.getOffsetAdjustment(),
          loadedContentHeight: loadedItems.getBoundingClientRect().height,
          rowHeight: measuredRow.getBoundingClientRect().height,
          groupHeaderHeight: measuredHeader.getBoundingClientRect().height,
          groupCount,
          contentPadding: 16,
        });
        setVirtualSpacerHeight((currentHeight) =>
          currentHeight === nextSpacerHeight ? currentHeight : nextSpacerHeight
        );
      } else {
        setVirtualSpacerHeight(0);
      }
      requestPage(false);
    };
    const scheduleMeasurement = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measureAndFill);
    };

    // Read layout synchronously after commit. A single animation-frame retry
    // covers transient zero-sized containers without delaying the page shell.
    measureAndFill();
    if (container.clientHeight <= 0) scheduleMeasurement();

    const resizeObserver = new ResizeObserver(scheduleMeasurement);
    resizeObserver.observe(container);
    if (loadedItemsRef.current) resizeObserver.observe(loadedItemsRef.current);
    return () => {
      resizeObserver.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [
    conversationMetadata,
    deletionRevision,
    requestPage,
    scrollContainerRef,
    threadCount,
  ]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    const sentinel = loadMoreSentinelRef.current;
    if (!container || !sentinel) return;

    previousScrollTopRef.current = container.scrollTop;
    const handleScrollIntent = () => {
      userScrollIntentRef.current = true;
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (["ArrowDown", "PageDown", "End"].includes(event.key)) {
        handleScrollIntent();
      }
    };
    const handleWheel = (event: WheelEvent) => {
      if (event.deltaY > 0) handleScrollIntent();
    };
    const handleScroll = (event: Event) => {
      const isScrollingDown =
        container.scrollTop > previousScrollTopRef.current;
      previousScrollTopRef.current = container.scrollTop;
      const hasUserIntent = userScrollIntentRef.current;
      userScrollIntentRef.current = false;
      if (event.isTrusted && hasUserIntent && isScrollingDown) {
        requestPage(true, true);
      }
    };
    container.addEventListener("pointerdown", handleScrollIntent);
    container.addEventListener("wheel", handleWheel, { passive: true });
    container.addEventListener("keydown", handleKeyDown);
    container.addEventListener("scroll", handleScroll, { passive: true });

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          requestPage(true, false);
        }
      },
      { root: container, threshold: 0 }
    );
    observer.observe(sentinel);
    return () => {
      observer.disconnect();
      container.removeEventListener("pointerdown", handleScrollIntent);
      container.removeEventListener("wheel", handleWheel);
      container.removeEventListener("keydown", handleKeyDown);
      container.removeEventListener("scroll", handleScroll);
    };
  }, [requestPage, scrollContainerRef]);

  return (
    <div className="flex flex-col p-2">
      <div
        aria-hidden="true"
        className="fixed invisible pointer-events-none -z-10"
      >
        <div
          ref={measurementRowRef}
          className="flex h-9 items-center rounded-lg px-3 text-sm"
        >
          Conversation
        </div>
        <div
          ref={measurementHeaderRef}
          className="px-3 pt-3 pb-1 text-xs font-medium"
        >
          {t("chat.threadList.today")}
        </div>
      </div>
      <div ref={loadedItemsRef} className="flex flex-col">
        <AuiIf
          condition={(s) =>
            s.threads.isLoading ||
            (s.threads.threadIds.length === 0 && s.threads.hasMore)
          }
        >
          <ThreadListSkeleton />
        </AuiIf>
        <AuiIf
          condition={(s) =>
            !s.threads.isLoading &&
            !s.threads.hasMore &&
            s.threads.threadIds.length === 0
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
            generatedTitles={generatedTitles}
            deleteWithPagination={deleteWithPagination}
          />
        </AuiIf>
      </div>
      <div
        ref={loadMoreSentinelRef}
        aria-hidden="true"
        className="h-px w-full shrink-0"
      />
      <div
        aria-hidden="true"
        className="w-full shrink-0"
        style={{ height: virtualSpacerHeight }}
      />
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
  generatedTitles?: ReadonlyMap<string, string>;
  deleteWithPagination: DeleteWithPagination;
}

const ThreadListItems: FC<ThreadListItemsProps> = ({
  generatedTitles,
  deleteWithPagination,
}) => {
  const { t } = useTranslation();

  const groups = useThreadListGroups();

  const GroupedThreadListItem = useCallback(
    function GroupedThreadListItem() {
      return (
        <ThreadListItem
          generatedTitles={generatedTitles}
          deleteWithPagination={deleteWithPagination}
        />
      );
    },
    [deleteWithPagination, generatedTitles]
  );

  if (!groups) {
    return (
      <ThreadListPrimitive.Items>
        {() => (
          <ThreadListItem
            generatedTitles={generatedTitles}
            deleteWithPagination={deleteWithPagination}
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

    const result: ThreadListGroup[] = [];
    for (const [index] of threadIds.entries()) {
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
  generatedTitles?: ReadonlyMap<string, string>;
  deleteWithPagination: DeleteWithPagination;
}

const ThreadListItem: FC<ThreadListItemProps> = ({
  generatedTitles,
  deleteWithPagination,
}) => {
  return (
    <ThreadListItemPrimitive.Root className="group/item flex h-9 items-center rounded-lg hover:bg-muted data-[active=true]:bg-muted">
      <ThreadListItemContent
        generatedTitles={generatedTitles}
        deleteWithPagination={deleteWithPagination}
      />
    </ThreadListItemPrimitive.Root>
  );
};

interface ThreadListItemContentProps {
  generatedTitles?: ReadonlyMap<string, string>;
  deleteWithPagination: DeleteWithPagination;
}

const ThreadListItemContent: FC<ThreadListItemContentProps> = ({
  generatedTitles,
  deleteWithPagination,
}) => {
  const aui = useAui();
  const { t } = useTranslation();
  const { confirm } = useConfirmModal();
  const [isEditing, setIsEditing] = useState(false);
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
          await deleteWithPagination(() => threadListItem.delete());
        } catch (error) {
          log.error("[ThreadList] Failed to delete thread:", error);
          message.error(t("chatInterface.deleteFailed"));
          throw error;
        } finally {
          setPendingThreadOperationId(undefined);
        }
      },
    });
  }, [confirm, deleteWithPagination, t, thread.id, threadListItem]);

  return (
    <>
      {isEditing ? (
        <InlineRenameEditor
          currentTitle={title}
          onRename={handleRename}
          onCancel={handleCancelRename}
        />
      ) : (
        <>
          <ThreadListItemPrimitive.Trigger className="flex min-w-0 flex-1 justify-start px-3 text-left text-sm">
            <div className="flex min-w-0 flex-1 items-center text-left">
              <ConversationStatusIndicatorWrapper />
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
        </>
      )}
      {!isEditing && (
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
const ConversationStatusIndicatorWrapper: FC = () => {
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
      className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden px-3"
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
        className="min-w-0 shrink flex-1 rounded border border-input px-2 py-1 text-sm outline-none focus:border-ring"
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
