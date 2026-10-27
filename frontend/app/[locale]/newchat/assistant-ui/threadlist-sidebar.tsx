// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  ChevronLeftIcon,
  PanelLeftIcon,
  SquarePen,
  SearchIcon,
  SquarePenIcon,
  XIcon,
} from "lucide-react";
import { WorkbenchPinHistorySync } from "./workbench-pin-history-sync";
import { getWorkbenchPinStorageKey } from "./thread-pins";
import { useConversationActivitySync } from "@/hooks/chat/useConversationActivitySync";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useEffect, useRef, useState } from "react";
import { message, Typography } from "antd";
import { StandardInput } from "@/components/common/StandardInput";
import { StandardButton } from "@/components/common/StandardButton";
import { ConversationExpandButton } from "@/components/common/ConversationExpandButton";
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarFooter,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import type { SidebarProps } from "@/components/ui/sidebar";
import { ThreadListPrimitive } from "@assistant-ui/react";
import {
  BatchSelectionProvider,
  BatchSidebarFooter,
  PinnedThreadsProvider,
  ThreadList,
} from "./thread-list";
import { useSidebar } from "@/components/ui/sidebar";
import { TooltipIconButton } from "../ui/tooltip-icon-button";
import { AgentSelectorDropdown } from "./agent-selector-dropdown";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import type { Agent } from "@/types/agentConfig";
import toolbarStyles from "@/components/common/ConversationToolbar.module.css";

type RenameSuccessHandler = (
  threadId: string,
  remoteId: string | undefined,
  title: string
) => void;

interface ThreadListSidebarProps extends SidebarProps {
  selectedAgent?: Agent | null;
  activeThreadId?: string;
  className?: string;
  generatedTitles?: ReadonlyMap<string, string>;
  serverConversationIds?: ReadonlyMap<string, string>;
  onPrepareNewConversation?: () => void;
  onNewConversation?: () => void | Promise<void>;
  onHistoryAgentSelected?: (agentId: number) => void;
  onRenameSuccess?: RenameSuccessHandler;
  onAgentSelected?: (agent: Agent) => void;
  newChatDesign?: boolean;
  collapseToHeader?: boolean;
  collapseToFloatingButton?: boolean;
  /** Accepted for backward compatibility; the design removed the legacy switch. */
  showLegacySwitch?: boolean;
  /** Optional explicit user scope; otherwise use the authenticated user's server pins. */
  pinStorageKey?: string | null;
}

export function ThreadListSidebar({
  selectedAgent,
  activeThreadId,
  generatedTitles,
  serverConversationIds,
  onPrepareNewConversation,
  onNewConversation,
  onAgentSelected,
  onHistoryAgentSelected,
  onRenameSuccess,
  newChatDesign = false,
  collapseToHeader = false,
  collapseToFloatingButton = false,
  pinStorageKey,
  ...props
}: ThreadListSidebarProps) {
  const { user } = useAuthorizationContext();
  const effectivePinScope =
    pinStorageKey !== undefined
      ? pinStorageKey
      : user
        ? getWorkbenchPinStorageKey(user.id, user.tenantId)
        : null;
  useConversationActivitySync(
    user ? `${user.id}:${user.tenantId}` : null,
    newChatDesign ? "agent_chat" : "workbench"
  );
  const { state, openMobile, toggleSidebar } = useSidebar();
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const compactCollapse = collapseToHeader || collapseToFloatingButton;
  const isDiscoveringAgents = newChatDesign && !selectedAgent;
  const selectedAgentId = selectedAgent ? Number(selectedAgent.id) : undefined;
  const isCollapsed =
    compactCollapse && isMobile
      ? !openMobile
      : state === "collapsed" || isMobile;
  const [searchOpen, setSearchOpen] = useState(false);
  const [conversationSearch, setConversationSearch] = useState("");
  const [legacySearchQuery, setLegacySearchQuery] = useState("");
  const floatingToolbarRef = useRef<HTMLDivElement>(null);
  const [isNarrowToolbar, setIsNarrowToolbar] = useState(false);
  useEffect(() => {
    if (
      !isCollapsed ||
      !collapseToFloatingButton ||
      (newChatDesign && !selectedAgent)
    )
      return;
    const page = floatingToolbarRef.current?.closest("[data-agent-chat-page]");
    if (!page) return;
    const updateDockPosition = () => {
      const bounds = page.getBoundingClientRect();
      setIsNarrowToolbar(bounds.width <= 1034);
    };
    const observer = new ResizeObserver(updateDockPosition);
    observer.observe(page);
    const frame = requestAnimationFrame(updateDockPosition);
    window.addEventListener("resize", updateDockPosition);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", updateDockPosition);
    };
  }, [isCollapsed, collapseToFloatingButton, newChatDesign, selectedAgent]);
  // Sidebar frame follows the new-chat page; the workbench mirrors it so the
  // left panel stays aligned when switching pages.
  const sidebarBackground = "#f6f7f8";

  if (isCollapsed && collapseToFloatingButton) {
    return (
      <div
        ref={floatingToolbarRef}
        data-floating-sidebar-trigger
        style={{ left: 12 }}
        data-expand-gutter={isNarrowToolbar || undefined}
        data-collapsed-agent-toolbar={
          !newChatDesign || selectedAgent ? "" : undefined
        }
        className={cn(
          "absolute left-3 top-3 z-20 flex w-max items-center gap-1",
          (!newChatDesign || selectedAgent) && toolbarStyles.toolbar
        )}
      >
        <ConversationExpandButton />
        {(!newChatDesign || selectedAgent) && (
          <>
            <TooltipIconButton
              tooltip={t("workbench.sidebar.newConversation")}
              variant="ghost"
              size="icon"
              className={cn("size-8 shrink-0", toolbarStyles.compose)}
              onClick={onNewConversation}
            >
              <SquarePen className="size-4" aria-hidden />
            </TooltipIconButton>
            {newChatDesign && selectedAgent && (
              <>
                <span
                  aria-hidden="true"
                  className={cn(
                    "mx-1 h-4 w-px shrink-0 bg-border",
                    toolbarStyles.separator
                  )}
                />
                <TooltipIconButton
                  tooltip={t("chat.sidebar.discoverAgents")}
                  variant="ghost"
                  size="icon"
                  className={cn("size-8 shrink-0", toolbarStyles.back)}
                  onClick={onPrepareNewConversation}
                >
                  <ChevronLeftIcon className="size-4" aria-hidden />
                </TooltipIconButton>
                <Typography.Text
                  ellipsis={{
                    tooltip: selectedAgent.display_name || selectedAgent.name,
                  }}
                  className={cn(
                    "min-w-0 flex-1 truncate whitespace-nowrap px-1 text-sm font-medium text-foreground",
                    toolbarStyles.name
                  )}
                >
                  {selectedAgent.display_name || selectedAgent.name}
                </Typography.Text>
              </>
            )}
          </>
        )}
      </div>
    );
  }

  if (isCollapsed && collapseToHeader) return null;

  if (isCollapsed) {
    return (
      <div className="h-full" style={{ backgroundColor: sidebarBackground }}>
        <Sidebar
          collapsible="none"
          className={cn(props.className, "!h-full")}
          style={{ backgroundColor: sidebarBackground, ...props.style }}
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
              {!newChatDesign && (
                <TooltipIconButton
                  tooltip={t("workbench.sidebar.newConversation")}
                  side="right"
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  onClick={onNewConversation}
                >
                  <SquarePen className="size-4" aria-hidden />
                </TooltipIconButton>
              )}
            </div>
          </SidebarHeader>
          <SidebarContent />
        </Sidebar>
      </div>
    );
  }

  return (
    <ThreadListPrimitive.Root asChild>
      <div
        className={cn(
          "h-full p-2",
          newChatDesign
            ? "w-[288px] min-w-[288px] max-w-[288px]"
            : "w-[296px] min-w-[296px] max-w-[296px]",
          compactCollapse && isMobile && "absolute z-30"
        )}
        style={{ backgroundColor: sidebarBackground }}
      >
        <PinnedThreadsProvider
          storageKey={effectivePinScope}
          serverBacked
          persistedConversationIds
          conversationType={newChatDesign ? "agent_chat" : "workbench"}
          serverConversationIds={serverConversationIds}
          onStorageError={
            effectivePinScope
              ? () => message.error(t("chat.threadList.pinServerFailed"))
              : undefined
          }
        >
          {effectivePinScope && (
            <WorkbenchPinHistorySync key={effectivePinScope} />
          )}
          <BatchSelectionProvider
            key={selectedAgentId ?? "discovery"}
            onNewConversation={onNewConversation}
            serverConversationIds={serverConversationIds}
            conversationType={newChatDesign ? "agent_chat" : "workbench"}
            selectedAgentId={selectedAgentId}
          >
            <Sidebar
              {...props}
              collapsible={compactCollapse && isMobile ? "offcanvas" : "none"}
              variant="inset"
              className={cn(props.className, "!h-full !w-full min-w-0")}
              style={{ backgroundColor: sidebarBackground, ...props.style }}
            >
              <SidebarHeader className="pb-0">
                <div className="flex flex-col gap-2 px-1">
                  {newChatDesign ? (
                    <div className="flex items-center gap-1">
                      {/* Back chevron: returns to the discover-agents landing
                          page (same handler the old filled button used). */}
                      {onPrepareNewConversation && !isDiscoveringAgents && (
                        <TooltipIconButton
                          tooltip={t("chat.sidebar.discoverAgents")}
                          variant="ghost"
                          size="icon"
                          className="size-8 shrink-0"
                          onClick={onPrepareNewConversation}
                        >
                          <ChevronLeftIcon className="size-4" />
                        </TooltipIconButton>
                      )}
                      {isDiscoveringAgents ? (
                        <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                          {t("sidebar.startChat")}
                        </span>
                      ) : onAgentSelected ? (
                        <div className="min-w-0 flex-1">
                          <AgentSelectorDropdown
                            selectedAgent={selectedAgent}
                            onAgentSelected={onAgentSelected}
                          />
                        </div>
                      ) : null}
                      <TooltipIconButton
                        tooltip={t("chat.sidebar.search")}
                        variant="ghost"
                        size="icon"
                        className="relative left-3 size-8 shrink-0"
                        onClick={() => {
                          setSearchOpen((open) => !open);
                          setConversationSearch("");
                        }}
                      >
                        <SearchIcon className="size-4" />
                      </TooltipIconButton>
                      <SidebarTrigger
                        aria-label={t("chatLeftSidebar.collapseSidebar")}
                        className="relative left-2 size-8 shrink-0 hover:bg-[#e5e7eb] hover:text-[#243447]"
                      />
                    </div>
                  ) : (
                    <>
                      <div
                        data-workbench-header-actions
                        className="flex h-8 items-center gap-2"
                      >
                        <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                          {t("workbench.sidebar.title")}
                        </span>
                        <TooltipIconButton
                          tooltip={t("chat.sidebar.search")}
                          variant="ghost"
                          size="icon"
                          className="size-8 shrink-0"
                          aria-expanded={searchOpen}
                          onClick={() => {
                            setSearchOpen((open) => !open);
                            setLegacySearchQuery("");
                          }}
                        >
                          <SearchIcon className="size-4" />
                        </TooltipIconButton>
                        <SidebarTrigger
                          aria-label={t("chatLeftSidebar.collapseSidebar")}
                          className="size-8 shrink-0"
                        />
                      </div>
                      {onNewConversation ? (
                        <StandardButton
                          variant="default"
                          className="!bg-white flex !h-9 min-w-0 !w-full items-center justify-center gap-2 !rounded-lg border border-[#d9d9d9] shadow-sm font-medium hover:brightness-95"
                          onClick={onNewConversation}
                        >
                          <SquarePen className="size-4 shrink-0" aria-hidden />
                          {t("workbench.sidebar.newConversation")}
                        </StandardButton>
                      ) : (
                        <ThreadListPrimitive.New
                          className="flex h-8 min-w-0 flex-1 items-center justify-center gap-2 rounded-lg border border-border bg-white px-3 text-sm text-[#191919]"
                          onClick={onPrepareNewConversation}
                        >
                          <SquarePen className="size-4 shrink-0" aria-hidden />
                          {t("workbench.sidebar.newConversation")}
                        </ThreadListPrimitive.New>
                      )}
                      {searchOpen && (
                        <div data-workbench-history-search>
                          <StandardInput
                            autoFocus
                            value={legacySearchQuery}
                            onChange={(event) =>
                              setLegacySearchQuery(event.target.value)
                            }
                            placeholder={t("chat.sidebar.searchHistory")}
                            aria-label={t("chat.sidebar.searchHistory")}
                            onKeyDown={(event) => {
                              if (event.key === "Escape") {
                                setSearchOpen(false);
                                setLegacySearchQuery("");
                              }
                            }}
                            suffix={
                              <button
                                type="button"
                                aria-label={t("chat.threadList.cancel")}
                                className="flex cursor-pointer items-center text-muted-foreground hover:text-foreground"
                                onClick={() => {
                                  setSearchOpen(false);
                                  setLegacySearchQuery("");
                                }}
                              >
                                <XIcon className="size-3.5" aria-hidden />
                              </button>
                            }
                          />
                        </div>
                      )}
                    </>
                  )}
                  {newChatDesign &&
                    !isDiscoveringAgents &&
                    onNewConversation && (
                      // Prominent pill per the design reference: white fill on
                      // the gray rail, compose glyph, centered label. Starts a
                      // blank conversation via the page's new-thread handler.
                      <button
                        type="button"
                        className="flex h-9 w-full cursor-pointer items-center justify-center gap-2 truncate rounded-lg border border-[#d9d9d9] bg-white text-[14px] font-medium text-[#191919] shadow-sm transition-colors hover:bg-[#f8f8f8]"
                        onClick={onNewConversation}
                      >
                        <SquarePenIcon className="size-4 shrink-0 text-primary" />
                        {t("chat.sidebar.newConversation")}
                      </button>
                    )}
                  {newChatDesign && searchOpen && (
                    // Toggled search field mirrors the pill's box (h-9,
                    // rounded-lg) and sits below it so the header reads as
                    // one evenly spaced stack.
                    <StandardInput
                      autoFocus
                      className="!h-9 !rounded-lg"
                      value={conversationSearch}
                      onChange={(event) =>
                        setConversationSearch(event.target.value)
                      }
                      placeholder={t("chat.sidebar.searchConversations")}
                      suffix={
                        <button
                          type="button"
                          aria-label={t("chat.threadList.cancel")}
                          className="flex cursor-pointer items-center text-[#808080] hover:text-[#191919]"
                          onClick={() => {
                            setSearchOpen(false);
                            setConversationSearch("");
                          }}
                        >
                          <XIcon className="size-3.5" aria-hidden />
                        </button>
                      }
                    />
                  )}
                </div>
              </SidebarHeader>
              <SidebarContent
                className={cn(
                  "focus:outline-none",
                  isDiscoveringAgents && toolbarStyles.discovery
                )}
              >
                <ThreadList
                  onHistoryAgentSelected={onHistoryAgentSelected}
                  activeThreadId={activeThreadId}
                  generatedTitles={generatedTitles}
                  serverConversationIds={serverConversationIds}
                  onRenameSuccess={onRenameSuccess}
                  searchQuery={
                    newChatDesign ? conversationSearch : legacySearchQuery
                  }
                  newChatDesign={newChatDesign}
                  selectedAgentId={selectedAgentId}
                />
              </SidebarContent>
              <SidebarFooter className="mt-auto p-0 empty:hidden">
                <BatchSidebarFooter />
              </SidebarFooter>
            </Sidebar>
          </BatchSelectionProvider>
        </PinnedThreadsProvider>
      </div>
    </ThreadListPrimitive.Root>
  );
}
