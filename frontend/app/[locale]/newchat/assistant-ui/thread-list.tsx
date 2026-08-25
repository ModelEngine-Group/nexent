"use client";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Button, message } from "antd";
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
import { Fragment, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import { cn } from "@/lib/utils";
import type { FC } from "react";

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
  selectedThreadIds: Set<string>;
  onToggleThreadSelect: (remoteId: string) => void;
}

export const ThreadList: FC<ThreadListProps> = ({
  generatedTitles,
  selectedThreadIds,
  onToggleThreadSelect,
}) => {
  const { t } = useTranslation();

  // Placeholder for completed set - currently not used since status only has completed/running
  const completedConversations = useMemo(() => new Set<string>(), []);

  return (
    <div className="contents p-2">
      <AuiIf condition={(s) => s.threads.isLoading}>
        <ThreadListSkeleton />
      </AuiIf>
      <AuiIf condition={(s) => !s.threads.isLoading && s.threads.threadIds.length === 0}>
        <ThreadListEmpty />
      </AuiIf>
      <AuiIf condition={(s) => !s.threads.isLoading && s.threads.threadIds.length > 0}>
        <ThreadListItems
          completedConversations={completedConversations}
          generatedTitles={generatedTitles}
          selectedThreadIds={selectedThreadIds}
          onToggleThreadSelect={onToggleThreadSelect}
        />
      </AuiIf>
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
  selectedThreadIds: Set<string>;
  onToggleThreadSelect: (remoteId: string) => void;
}

const ThreadListItems: FC<ThreadListItemsProps> = ({
  completedConversations,
  generatedTitles,
  selectedThreadIds,
  onToggleThreadSelect,
}) => {
  const { t } = useTranslation();

  const groups = useThreadListGroups();


  const GroupedThreadListItem = useMemo<FC>(
    () => () => (
      <ThreadListItem
        completedConversations={completedConversations}
        generatedTitles={generatedTitles}
        selectedThreadIds={selectedThreadIds}
        onToggleThreadSelect={onToggleThreadSelect}
      />
    ),
    [completedConversations, generatedTitles, selectedThreadIds, onToggleThreadSelect],
  );

  if (!groups) {
    return (
      <ThreadListPrimitive.Items>
        {() => (
          <ThreadListItem
            completedConversations={completedConversations}
            generatedTitles={generatedTitles}
            selectedThreadIds={selectedThreadIds}
            onToggleThreadSelect={onToggleThreadSelect}
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
  startOfToday: number,
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
      (threadItems as ReadonlyArray<{
        id: string;
        custom?: { lastMessageAt?: string };
      }>).map((item) => [item.id, item]),
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
      now.getDate(),
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
  selectedThreadIds: Set<string>;
  onToggleThreadSelect: (remoteId: string) => void;
}

const ThreadListItem: FC<ThreadListItemProps> = ({
  completedConversations,
  generatedTitles,
  selectedThreadIds,
  onToggleThreadSelect,
}) => {
  const aui = useAui();
  const remoteId = aui.threadListItem.getState().remoteId;
  const isSelected = remoteId ? selectedThreadIds.has(remoteId) : false;
  return (
    <ThreadListItemPrimitive.Root
      className={cn(
        "group/item flex h-9 items-center rounded-lg hover:bg-muted data-[active=true]:bg-muted",
        isSelected && "bg-[#DCE9FF] hover:bg-[#DCE9FF]",
      )}
    >
      <ThreadListItemContent
        completedConversations={completedConversations}
        generatedTitles={generatedTitles}
        selectedThreadIds={selectedThreadIds}
        onToggleThreadSelect={onToggleThreadSelect}
      />
    </ThreadListItemPrimitive.Root>
  );
};

interface ThreadListItemContentProps {
  completedConversations: Set<string>;
  generatedTitles?: ReadonlyMap<string, string>;
  selectedThreadIds: Set<string>;
  onToggleThreadSelect: (remoteId: string) => void;
}

const ThreadListItemContent: FC<ThreadListItemContentProps> = ({
  completedConversations,
  generatedTitles,
  selectedThreadIds,
  onToggleThreadSelect,
}) => {
  const aui = useAui();
  const { t } = useTranslation();
  const { confirm } = useConfirmModal();
  const [isEditing, setIsEditing] = useState(false);
  const threadListItem = aui.threadListItem;
  const thread = threadListItem.getState();
  const title = generatedTitles?.get(thread.id) ?? thread.title ?? t("chat.thread.newChat");
  const remoteId = thread.remoteId;
  const isSelected = remoteId ? selectedThreadIds.has(remoteId) : false;

  const handleRename = useCallback(async (newTitle: string) => {
    try {
      await threadListItem.rename(newTitle);
      log.log(`[ThreadList] Renamed thread to "${newTitle}"`);
      setIsEditing(false);
    } catch (error) {
      log.error("[ThreadList] Failed to rename thread:", error);
      message.error(t("chat.threadList.renameFailed"));
    }
  }, [threadListItem, t]);

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
        try {
          await threadListItem.delete();
        } catch (error) {
          log.error("[ThreadList] Failed to delete thread:", error);
          message.error(t("chatInterface.deleteFailed"));
          throw error;
        }
      },
    });
  }, [confirm, t, threadListItem]);

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
          {!isEditing && remoteId && (
            <input
              type="checkbox"
              checked={isSelected}
              onClick={(e) => e.stopPropagation()}
              onChange={() => onToggleThreadSelect(remoteId)}
              className="ml-2 mr-1 size-4 shrink-0 cursor-pointer rounded border-input accent-[#4379EE]"
              aria-label={t("chat.threadList.batch.select")}
            />
          )}
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
const ConversationStatusIndicatorWrapper: FC<{
  completedConversations: Set<string>;
}> = ({ completedConversations }) => {
  const aui = useAui();
  const status = aui.threadListItem.getState().status as string;
  const isRunning = status === "running" || status === "streaming";

  return (
    <ConversationStatusIndicator
      isStreaming={isRunning}
      isCompleted={false}
    />
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
    [title, currentTitle, onRename, onCancel],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        onCancel();
      }
    },
    [onCancel],
  );

  return (
    <form
      onSubmit={handleSubmit}
      className="flex min-w-0 flex-1 items-center gap-1 px-3"
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
        className="flex-1 bg-background border border-input rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
      <button
        type="submit"
        className="p-1 hover:bg-accent rounded"
      >
        <CheckIcon className="size-4" />
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="p-1 hover:bg-accent rounded"
      >
        <XIcon className="size-4" />
      </button>
    </form>
  );
};

