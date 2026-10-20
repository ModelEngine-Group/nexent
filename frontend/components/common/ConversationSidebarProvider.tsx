// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ComponentProps } from "react";
import { SidebarProvider } from "@/components/ui/sidebar";
import { useConversationSidebarStore } from "@/stores/conversationSidebarStore";

interface ConversationSidebarProviderProps extends Omit<
  ComponentProps<typeof SidebarProvider>,
  "open" | "onOpenChange" | "defaultOpen"
> {
  scope: "workbench" | "agent-chat";
}

export function ConversationSidebarProvider({
  scope,
  ...props
}: ConversationSidebarProviderProps) {
  const open = useConversationSidebarStore((state) => state.open[scope]);
  const setOpen = useConversationSidebarStore((state) => state.setOpen);
  return (
    <SidebarProvider
      {...props}
      open={open}
      onOpenChange={(value) => setOpen(scope, value)}
    />
  );
}
