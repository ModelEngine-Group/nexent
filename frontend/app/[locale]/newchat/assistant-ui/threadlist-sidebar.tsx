import type * as React from "react";
import { PanelLeftIcon, PlusIcon, MessageSquareIcon } from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import type { SidebarProps } from "@/components/ui/sidebar";
import {
  ThreadListPrimitive,
  ThreadListItemPrimitive,
  ThreadListItemMorePrimitive,
} from "@assistant-ui/react";
import { ThreadList } from "./thread-list";
import { useSidebar } from "@/components/ui/sidebar";
import { TooltipIconButton } from "../ui/tooltip-icon-button";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";


interface ThreadListSidebarProps extends SidebarProps {
  className?: string;
  generatedTitles?: ReadonlyMap<string, string>;
}

export function ThreadListSidebar({
  generatedTitles,
  ...props
}: ThreadListSidebarProps) {
  const { state, toggleSidebar } = useSidebar();
  const isMobile = useIsMobile();
  const isCollapsed = state === "collapsed" || isMobile;

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
                tooltip="展开"
                side="right"
                variant="ghost"
                size="icon"
                className="size-8"
                onClick={toggleSidebar}
              >
                <PanelLeftIcon className="size-4" />
              </TooltipIconButton>
              <TooltipIconButton
                tooltip="新对话"
                side="right"
                variant="ghost"
                size="icon"
                className="size-8"
              >
                <PlusIcon className="size-4" />
              </TooltipIconButton>
            </div>
          </SidebarHeader>
          <SidebarContent />
          <SidebarFooter />
        </Sidebar>
      </div>
    );
  }

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
              <ThreadListPrimitive.New className="flex h-9 flex-1 items-center gap-2 rounded-lg border px-3 text-sm hover:bg-muted truncate">
                <PlusIcon className="size-4 shrink-0" />
                新对话
              </ThreadListPrimitive.New>
              <SidebarTrigger className="size-8 shrink-0" />
            </div>
          </SidebarHeader>
          <SidebarContent>
            <ThreadList generatedTitles={generatedTitles} />
          </SidebarContent>
          <SidebarFooter />
        </Sidebar>
      </div>
    </ThreadListPrimitive.Root>
  );
}


