// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  ChevronLeftIcon,
  PanelLeftIcon,
  SquarePen,
  SearchIcon,
  SquarePenIcon,
  XIcon,
} from "lucide-react";
import { useState } from "react";
import { message } from "antd";
import { StandardInput } from "@/components/common/StandardInput";
import { StandardButton } from "@/components/common/StandardButton";
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarFooter,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import type { SidebarProps } from "@/components/ui/sidebar";
import {
  ThreadListPrimitive,
  ThreadListItemPrimitive,
  ThreadListItemMorePrimitive,
} from "@assistant-ui/react";
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
  onRenameSuccess?: RenameSuccessHandler;
  onAgentSelected?: (agent: Agent) => void;
  newChatDesign?: boolean;
  /** Accepted for backward compatibility; the design removed the legacy switch. */
  showLegacySwitch?: boolean;
  /** Workbench uses user-scoped server IDs; undefined retains Agent-chat pins. */
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
  onRenameSuccess,
  newChatDesign = false,
  pinStorageKey,
  ...props
}: ThreadListSidebarProps) {
  const { state, toggleSidebar } = useSidebar();
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const isCollapsed = state === "collapsed" || isMobile;
  const [searchOpen, setSearchOpen] = useState(false);
  const [conversationSearch, setConversationSearch] = useState("");
  const [legacySearchQuery, setLegacySearchQuery] = useState("");
  // Sidebar frame follows the new-chat page; the workbench mirrors it so the
  // left panel stays aligned when switching pages.
  const sidebarBackground = "#f0f0f0";

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
        className={cn("h-full w-[296px] min-w-[296px] max-w-[296px] p-2")}
        style={{ backgroundColor: sidebarBackground }}
      >
        <PinnedThreadsProvider
          storageKey={pinStorageKey}
          serverBacked={pinStorageKey !== undefined}
          persistedConversationIds={pinStorageKey !== undefined}
          serverConversationIds={serverConversationIds}
          onStorageError={
            pinStorageKey !== undefined
              ? () => message.error(t("chat.threadList.pinServerFailed"))
              : undefined
          }
        >
          <BatchSelectionProvider
            onNewConversation={onNewConversation}
            serverConversationIds={serverConversationIds}
            conversationType={newChatDesign ? "agent_chat" : "workbench"}
          >
            <Sidebar
              {...props}
              collapsible="none"
              variant="inset"
              className={cn(props.className, "!h-full !w-full min-w-0")}
              style={{ backgroundColor: sidebarBackground, ...props.style }}
            >
              <SidebarHeader className="pb-0">
                <div className="flex flex-col gap-2 px-1">
                  {newChatDesign ? (
                    <div className="flex items-center gap-1">
                      {/* Back chevron: returns to the discover-agents landing
                          page (same handler the old filled button used).
                          -mr-3 pulls the dropdown trigger over the button's
                          inner padding so the title sits close to the glyph. */}
                      {onPrepareNewConversation && (
                        <TooltipIconButton
                          tooltip={t("chat.sidebar.discoverAgents")}
                          variant="ghost"
                          size="icon"
                          className="size-8 shrink-0 -mr-3"
                          onClick={onPrepareNewConversation}
                        >
                          <ChevronLeftIcon className="size-4" />
                        </TooltipIconButton>
                      )}
                      {onAgentSelected && (
                        <div className="min-w-0 flex-1">
                          <AgentSelectorDropdown
                            selectedAgent={selectedAgent}
                            onAgentSelected={onAgentSelected}
                          />
                        </div>
                      )}
                      <TooltipIconButton
                        tooltip={t("chat.sidebar.search")}
                        variant="ghost"
                        size="icon"
                        className="size-8 shrink-0"
                        onClick={() => {
                          setSearchOpen((open) => !open);
                          setConversationSearch("");
                        }}
                      >
                        <SearchIcon className="size-4" />
                      </TooltipIconButton>
                      <SidebarTrigger className="size-8 shrink-0" />
                    </div>
                  ) : (
                    <>
                      <div
                        data-workbench-header-actions
                        className="flex h-8 items-center gap-2"
                      >
                        {onNewConversation ? (
                          <StandardButton
                            variant="default"
                            className="!bg-white flex !h-8 min-w-0 flex-1 !w-auto items-center justify-center gap-2 !rounded-lg font-medium hover:brightness-95"
                            onClick={onNewConversation}
                          >
                            <SquarePen
                              className="size-4 shrink-0"
                              aria-hidden
                            />
                            {t("workbench.sidebar.newConversation")}
                          </StandardButton>
                        ) : (
                          <ThreadListPrimitive.New
                            className="flex h-8 min-w-0 flex-1 items-center justify-center gap-2 rounded-lg border border-border bg-white px-3 text-sm text-[#191919]"
                            onClick={onPrepareNewConversation}
                          >
                            <SquarePen
                              className="size-4 shrink-0"
                              aria-hidden
                            />
                            {t("workbench.sidebar.newConversation")}
                          </ThreadListPrimitive.New>
                        )}
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
                        <SidebarTrigger className="size-8 shrink-0" />
                      </div>
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
                  {newChatDesign && onNewConversation && (
                    // Prominent pill per the design reference: white fill on
                    // the gray rail, compose glyph, centered label. Starts a
                    // blank conversation via the page's new-thread handler.
                    <button
                      type="button"
                      className="flex h-9 w-full cursor-pointer items-center justify-center gap-2 truncate rounded-lg bg-white text-[14px] font-medium text-[#191919] transition-colors hover:bg-[#e8e8e8]"
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
              <SidebarContent className="focus:outline-none">
                <ThreadList
                  activeThreadId={activeThreadId}
                  generatedTitles={generatedTitles}
                  serverConversationIds={serverConversationIds}
                  onRenameSuccess={onRenameSuccess}
                  searchQuery={
                    newChatDesign ? conversationSearch : legacySearchQuery
                  }
                  newChatDesign={newChatDesign}
                />
              </SidebarContent>
              <SidebarFooter>
                <BatchSidebarFooter />
              </SidebarFooter>
            </Sidebar>
          </BatchSelectionProvider>
        </PinnedThreadsProvider>
      </div>
    </ThreadListPrimitive.Root>
  );
}
