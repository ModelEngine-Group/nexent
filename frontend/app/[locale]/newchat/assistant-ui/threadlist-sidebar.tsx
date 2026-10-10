import {
  PanelLeftIcon,
  PlusIcon,
  SearchIcon,
  Sparkle,
  XIcon,
} from "lucide-react";
import { useState } from "react";
import { StandardInput } from "@/components/common/StandardInput";
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
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

interface ThreadListSidebarProps extends SidebarProps {
  selectedAgent?: Agent | null;
  activeThreadId?: string;
  className?: string;
  generatedTitles?: ReadonlyMap<string, string>;
  onPrepareNewConversation?: () => void;
  onNewConversation?: () => void | Promise<void>;
  onAgentSelected?: (agent: Agent) => void;
  newChatDesign?: boolean;
  /** Accepted for backward compatibility; the design removed the legacy switch. */
  showLegacySwitch?: boolean;
}

// "Discover agents" glyph: a magnifier with a sparkle at its top-right,
// matching the design's AI-discovery icon.
function DiscoverAgentsIcon({ className }: { className?: string }) {
  return (
    <span className={cn("relative inline-flex shrink-0", className)}>
      <SearchIcon className="size-4" aria-hidden />
      <Sparkle
        className="absolute -right-1 -top-1 size-2 fill-current"
        aria-hidden
      />
    </span>
  );
}

export function ThreadListSidebar({
  selectedAgent,
  activeThreadId,
  generatedTitles,
  onPrepareNewConversation,
  onNewConversation,
  onAgentSelected,
  newChatDesign = false,
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
                  tooltip={t("chat.sidebar.newConversation")}
                  side="right"
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  onClick={onNewConversation}
                >
                  <PlusIcon className="size-4" />
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
          "h-full",
          newChatDesign
            ? "w-[296px] min-w-[296px] max-w-[296px] p-2"
            : "w-[360px] min-w-[360px] max-w-[360px] p-2"
        )}
        style={{ backgroundColor: sidebarBackground }}
      >
        <PinnedThreadsProvider>
          <BatchSelectionProvider onNewConversation={onNewConversation}>
            <Sidebar
              {...props}
              collapsible="none"
              variant="inset"
              className={cn(props.className, "!h-full !w-full min-w-0")}
              style={{ backgroundColor: sidebarBackground, ...props.style }}
            >
              <SidebarHeader>
                <div className="flex flex-col gap-2 px-1">
                  {newChatDesign ? (
                    <div className="flex items-center gap-1">
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
                    <div className="flex h-9 items-center gap-2 rounded-lg border border-border bg-white px-2">
                      <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
                      <input
                        value={legacySearchQuery}
                        onChange={(event) =>
                          setLegacySearchQuery(event.target.value)
                        }
                        placeholder={t("chat.sidebar.searchHistory")}
                        aria-label={t("chat.sidebar.searchHistory")}
                        className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                      />
                      <SidebarTrigger className="size-8 shrink-0" />
                    </div>
                  )}
                  {newChatDesign && searchOpen && (
                    <StandardInput
                      autoFocus
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
                  {newChatDesign ? (
                    <ThreadListPrimitive.New
                      className="flex h-9 w-full items-center gap-2 rounded-lg border px-3 text-sm hover:bg-muted truncate bg-[#e4e4e4] border-[#e4e4e4]"
                      onClick={onPrepareNewConversation}
                    >
                      <DiscoverAgentsIcon className="size-4" />
                      {t("chat.sidebar.discoverAgents")}
                    </ThreadListPrimitive.New>
                  ) : (
                    <ThreadListPrimitive.New
                      className="flex h-9 flex-1 items-center gap-2 rounded-lg px-3 text-sm hover:bg-muted truncate"
                      onClick={onPrepareNewConversation}
                    >
                      <PlusIcon className="size-4 shrink-0" />
                      {t("chat.sidebar.newConversation")}
                    </ThreadListPrimitive.New>
                  )}
                </div>
              </SidebarHeader>
              <SidebarContent className="focus:outline-none">
                <ThreadList
                  activeThreadId={activeThreadId}
                  generatedTitles={generatedTitles}
                  searchQuery={
                    newChatDesign ? conversationSearch : legacySearchQuery
                  }
                  newChatDesign={newChatDesign}
                />
              </SidebarContent>
            </Sidebar>
          </BatchSelectionProvider>
        </PinnedThreadsProvider>
      </div>
    </ThreadListPrimitive.Root>
  );
}
