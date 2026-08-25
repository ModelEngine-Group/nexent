import type * as React from "react";
import { useRouter } from "next/navigation";
import { PanelLeftIcon, PlusIcon, Repeat2Icon, Trash2Icon, XIcon } from "lucide-react";
import { Button, message } from "antd";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import type { SidebarProps } from "@/components/ui/sidebar";
import { ThreadListPrimitive } from "@assistant-ui/react";
import { ThreadList } from "./thread-list";
import { useSidebar } from "@/components/ui/sidebar";
import { TooltipIconButton } from "../ui/tooltip-icon-button";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { conversationService } from "@/services/conversationService";
import { getAutomationConversationIds } from "@/features/agentAutomation/chatAdapter";
import log from "@/lib/logger";
import { useCallback, useState } from "react";


interface ThreadListSidebarProps extends SidebarProps {
  className?: string;
  generatedTitles?: ReadonlyMap<string, string>;
  onPrepareNewConversation?: () => void;
  onNewConversation?: () => void | Promise<void>;
  onReloadThreadList?: () => Promise<void>;
  activeRemoteId?: string;
  onSwitchToNewThread?: () => void | Promise<void>;
}

export function ThreadListSidebar({
  generatedTitles,
  onPrepareNewConversation,
  onNewConversation,
  onReloadThreadList,
  activeRemoteId,
  onSwitchToNewThread,
  ...props
}: ThreadListSidebarProps) {
  const { state, toggleSidebar } = useSidebar();
  const { t } = useTranslation();
  const { confirm } = useConfirmModal();
  const router = useRouter();
  const isMobile = useIsMobile();
  const isCollapsed = state === "collapsed" || isMobile;
  const [selectedThreadIds, setSelectedThreadIds] = useState<Set<string>>(
    () => new Set(),
  );

  const handleToggleThreadSelect = useCallback((remoteId: string) => {
    setSelectedThreadIds((prev) => {
      const next = new Set(prev);
      if (next.has(remoteId)) {
        next.delete(remoteId);
      } else {
        next.add(remoteId);
      }
      return next;
    });
  }, []);

  const handleBatchDelete = useCallback(async () => {
    if (selectedThreadIds.size === 0) return;

    let hasAutomation = false;
    try {
      const automationIds = await getAutomationConversationIds();
      const selectedNums = [...selectedThreadIds].map(Number);
      hasAutomation = selectedNums.some((id) => automationIds.has(id));
    } catch (error) {
      log.warn("Failed to check automation for batch delete", error);
    }

    const count = selectedThreadIds.size;
    confirm({
      title: t("chat.threadList.batch.delete"),
      content: hasAutomation
        ? t("chat.threadList.batch.confirmWithAutomation", { count })
        : t("chat.threadList.batch.confirm", { count }),
      onOk: async () => {
        try {
          await conversationService.batchDelete(
            [...selectedThreadIds].map(Number),
          );
          const includesActive = activeRemoteId
            ? selectedThreadIds.has(activeRemoteId)
            : false;
          setSelectedThreadIds(new Set());
          await onReloadThreadList?.();
          if (includesActive) {
            await onSwitchToNewThread?.();
          }
        } catch (error) {
          log.error("[ThreadList] Failed to batch delete:", error);
          message.error(t("chatInterface.deleteFailed"));
          throw error;
        }
      },
    });
  }, [
    selectedThreadIds,
    confirm,
    t,
    activeRemoteId,
    onReloadThreadList,
    onSwitchToNewThread,
  ]);

  const handleClearSelection = useCallback(() => {
    setSelectedThreadIds(new Set());
  }, []);

  if (isCollapsed) {
    return (
      <div className="h-full" style={{ backgroundColor: "#F2F8FF" }}>
        <Sidebar
          collapsible="none"
          className={cn(props.className, "!h-full")}
          style={{backgroundColor: "#F2F8FF", ...props.style}}
          {...props}
        >
          <SidebarHeader>
            <div className="flex flex-col items-center gap-2 p-1.5">
              <TooltipIconButton
                tooltip={t("chat.sidebar.expand")}
                side="right"
                variant="ghost"
                size="icon"
                className="size-8"
                onClick={toggleSidebar}
              >
                <PanelLeftIcon className="size-4" />
              </TooltipIconButton>
              <TooltipIconButton
                tooltip={t("chat.sidebar.newConversation")}
                side="right"
                variant="ghost"
                size="icon"
                className="size-8"
                onClick={onNewConversation}
              >
                <PlusIcon className="size-4" />
              </TooltipIconButton>
            </div>
          </SidebarHeader>
          <SidebarContent />
          <SidebarFooter>
            <TooltipIconButton
              tooltip={t("chat.sidebar.switchToLegacy")}
              side="right"
              variant="ghost"
              size="icon"
              className="size-8"
              onClick={() => router.push("/chat")}
            >
              <Repeat2Icon className="size-4" />
            </TooltipIconButton>
          </SidebarFooter>
        </Sidebar>
      </div>
    );
  }

  const hasSelection = selectedThreadIds.size > 0;

  return (
    <ThreadListPrimitive.Root asChild>
      <div
        className="h-full w-64 min-w-64 max-w-64 p-2"
        style={{ backgroundColor: "#F2F8FF" }}
      >
        <Sidebar
          {...props}
          collapsible="none"
          variant="inset"
          className={cn(props.className, "!h-full !w-full min-w-0")}
          style={{ backgroundColor: "#F2F8FF", ...props.style }}
        >
          <SidebarHeader>
            <div className="flex items-center gap-2 px-1">
              <ThreadListPrimitive.New
                className="flex h-9 flex-1 items-center gap-2 rounded-lg border px-3 text-sm hover:bg-muted truncate"
                onClick={onPrepareNewConversation}
              >
                <PlusIcon className="size-4 shrink-0" />
                {t("chat.sidebar.newConversation")}
              </ThreadListPrimitive.New>
              <SidebarTrigger className="size-8 shrink-0" />
            </div>
            {hasSelection && (
              <div
                data-slot="aui_thread-list-batch-bar"
                className="mt-2 flex items-center gap-1 rounded-lg px-2 py-1.5"
                style={{ backgroundColor: "#DCE9FF" }}
              >
                <span className="flex-1 truncate text-xs font-medium text-[#4379EE]">
                  {t("chat.threadList.batch.selectedCount", {
                    count: selectedThreadIds.size,
                  })}
                </span>
                <Button
                  size="small"
                  type="text"
                  className="!px-1.5 !py-0"
                  icon={<XIcon className="size-3.5" />}
                  onClick={handleClearSelection}
                >
                  {t("chat.threadList.batch.clear")}
                </Button>
                <Button
                  size="small"
                  danger
                  type="primary"
                  className="!px-2 !py-0"
                  icon={<Trash2Icon className="size-3.5" />}
                  onClick={handleBatchDelete}
                >
                  {t("chat.threadList.batch.delete")}
                </Button>
              </div>
            )}
          </SidebarHeader>
          <SidebarContent>
            <ThreadList
              generatedTitles={generatedTitles}
              selectedThreadIds={selectedThreadIds}
              onToggleThreadSelect={handleToggleThreadSelect}
            />
          </SidebarContent>
          <SidebarFooter>
            <button
              type="button"
              className="flex h-9 w-full items-center justify-center gap-2 rounded-lg border px-3 text-sm hover:bg-muted"
              onClick={() => router.push("/chat")}
            >
              <Repeat2Icon className="size-4 shrink-0" />
              <span>{t("chat.sidebar.switchToLegacy")}</span>
            </button>
          </SidebarFooter>
        </Sidebar>
      </div>
    </ThreadListPrimitive.Root>
  );
}
