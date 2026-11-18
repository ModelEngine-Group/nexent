// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { createContext, useContext } from "react";
import type { ClarificationResponse } from "@/types/clarification";

export interface CreationModeConfirmation {
  canCreateAgent: boolean;
  canCreateSkill: boolean;
  confirm: (request: {
    threadId: string;
    messageId: string;
    originalRequest: string;
    response: ClarificationResponse;
  }) => Promise<void>;
}

export const CreationModeConfirmationContext =
  createContext<CreationModeConfirmation | null>(null);
export const useCreationModeConfirmationContext = () =>
  useContext(CreationModeConfirmationContext);
