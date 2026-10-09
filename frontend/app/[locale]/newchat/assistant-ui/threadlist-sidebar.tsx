import { useState } from "react";
import { PanelLeftIcon, PlusIcon, SearchIcon } from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import type { SidebarProps } from "@/components/ui/sidebar";
import { ThreadListPrimitive } from "@assistant-ui/react";
import { BatchSelectionProvider, ThreadList } from "./thread-list";
import { useSidebar } from "@/components/ui/sidebar";
import { TooltipIconButton } from "../ui/tooltip-icon-button";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";

interface ThreadListSidebarProps extends SidebarProps {
  className?: string;
  generatedTitles?: ReadonlyMap<string, string>;
  onPrepareNewConversation?: () => void;
  onNewConversation?: () => void | Promise<void>;
  showLegacySwitch?: boolean;
}

export function ThreadListSidebar({
  generatedTitles,
  onPrepareNewConversation,
  onNewConversation,
  ...props
}: ThreadListSidebarProps) {
  const { state, toggleSidebar } = useSidebar();
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const isCollapsed = state === "collapsed" || isMobile;
  const [searchQuery, setSearchQuery] = useState("");

  if (isCollapsed) {
    return (
      <div className="h-full" style={{ backgroundColor: "#FFFFFF" }}>
        <Sidebar
          collapsible="none"
          className={cn(props.className, "!h-full")}
          style={{ backgroundColor: "#FFFFFF", ...props.style }}
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
        </Sidebar>
      </div>
    );
  }

  return (
    <ThreadListPrimitive.Root asChild>
      <div
        className="h-full w-64 min-w-64 max-w-64"
        style={{ backgroundColor: "#FFFFFF" }}
      >
        <BatchSelectionProvider onNewConversation={onNewConversation}>
          <Sidebar
            {...props}
            collapsible="none"
            className={cn(
              props.className,
              "!h-full !w-full min-w-0 [&_[data-sidebar=sidebar]]:bg-white"
            )}
            style={{ backgroundColor: "#FFFFFF", ...props.style }}
          >
            <SidebarHeader>
              <div className="flex flex-col gap-2 px-1">
                <div className="flex h-9 items-center gap-2 rounded-lg border border-border bg-white px-2">
                  <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
                  <input
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    placeholder={t("chat.sidebar.searchHistory")}
                    aria-label={t("chat.sidebar.searchHistory")}
                    className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                  />
                  <SidebarTrigger className="size-8 shrink-0" />
                </div>
                <ThreadListPrimitive.New
                  className="flex h-9 flex-1 items-center gap-2 rounded-lg px-3 text-sm hover:bg-muted truncate"
                  onClick={onPrepareNewConversation}
                >
                  <PlusIcon className="size-4 shrink-0" />
                  {t("chat.sidebar.newConversation")}
                </ThreadListPrimitive.New>
              </div>
            </SidebarHeader>
            <SidebarContent className="focus:outline-none">
              <ThreadList
                generatedTitles={generatedTitles}
                searchQuery={searchQuery}
              />
              {/* AgentGroupsPanel (design component demo) removed from the
                  sidebar until its placement is confirmed. */}
            </SidebarContent>
          </Sidebar>
        </BatchSelectionProvider>
      </div>
    </ThreadListPrimitive.Root>
  );
}
