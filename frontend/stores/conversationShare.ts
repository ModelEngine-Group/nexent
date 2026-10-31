// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { create } from "zustand";

interface ShareRequest {
  threadId: string;
  conversationId: number;
}

export const useConversationShareRequest = create<{
  request: ShareRequest | null;
  setRequest: (request: ShareRequest | null) => void;
}>((set) => ({ request: null, setRequest: (request) => set({ request }) }));
