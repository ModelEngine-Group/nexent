// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { TFunction } from "i18next";

import { ApiError } from "@/services/api";

const AUTOMATION_ERROR_KEYS: Record<string, string> = {
  AUTOMATION_ERROR: "agentAutomation.errors.generic",
  AUTOMATION_MODEL_UNAVAILABLE: "agentAutomation.errors.modelUnavailable",
  AUTOMATION_CAPABILITY_NOT_READY: "agentAutomation.errors.capabilityNotReady",
  AUTOMATION_CAPABILITY_UNAVAILABLE:
    "agentAutomation.errors.capabilityUnavailable",
  AUTOMATION_CAPABILITY_BINDING_INVALID:
    "agentAutomation.errors.capabilityBindingInvalid",
  AUTOMATION_SCHEDULE_INVALID: "agentAutomation.errors.scheduleInvalid",
  AUTOMATION_TASK_NOT_FOUND: "agentAutomation.errors.taskNotFound",
  AUTOMATION_CONVERSATION_ALREADY_BOUND:
    "agentAutomation.errors.conversationAlreadyBound",
};

export function translateAutomationErrorCode(
  code: string | number | null | undefined,
  t: (key: string) => string
): string | undefined {
  const key = AUTOMATION_ERROR_KEYS[String(code)];
  return key ? t(key) : undefined;
}

export function getAutomationErrorMessage(
  error: unknown,
  t: TFunction,
  fallbackKey: string
): string {
  if (error instanceof ApiError) {
    return translateAutomationErrorCode(error.code, t) ?? t(fallbackKey);
  }
  return t(fallbackKey);
}
