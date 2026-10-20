// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { create } from "zustand";

interface ConversationSidebarState {
  open: Record<"workbench" | "agent-chat", boolean>;
  setOpen: (scope: "workbench" | "agent-chat", open: boolean) => void;
}

// Memory only: route changes retain visibility, while a new document resets it.
export const useConversationSidebarStore = create<ConversationSidebarState>(
  (set) => ({
    open: { workbench: true, "agent-chat": true },
    setOpen: (scope, open) =>
      set((state) => ({ open: { ...state.open, [scope]: open } })),
  })
);
