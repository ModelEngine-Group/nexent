// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { createContext } from "react";

export const ConversationShareContext = createContext<{
  disabled: boolean;
  shareTurn: (assistantMessageId: string) => void;
} | null>(null);
