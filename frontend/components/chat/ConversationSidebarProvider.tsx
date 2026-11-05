// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState, type ComponentProps } from "react";
import { SidebarProvider } from "@/components/ui/sidebar";

type ConversationSidebarProviderProps = Omit<
  ComponentProps<typeof SidebarProvider>,
  "open" | "onOpenChange" | "defaultOpen"
>;

export function ConversationSidebarProvider(
  props: ConversationSidebarProviderProps
) {
  const [open, setOpen] = useState(true);
  return <SidebarProvider {...props} open={open} onOpenChange={setOpen} />;
}
