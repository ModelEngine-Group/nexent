// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18next from "i18next";

interface RunErrorEvent {
  content?: string;
  error_code?: string;
  request_id?: string | null;
}

const reasons = new Map([
  ["NEXENT_TERMINAL_MISSING", "chat.runError.terminalMissing"],
  ["JIUWEN_INVALID_CLARIFICATION", "chat.runError.invalidClarification"],
  ["INVALID_TOOL_ARGUMENTS", "chat.runError.invalidToolArguments"],
  ["JIUWEN_EXECUTION_FAILED", "chat.runError.executionFailed"],
]);

export function describeConversationRunError(event: RunErrorEvent) {
  const code = event.error_code || event.content?.trim();
  const reason = code && reasons.get(code);
  if (!reason) return undefined;

  const content = event.content?.trim();
  return {
    text:
      code === "NEXENT_TERMINAL_MISSING" || !content || content === code
        ? i18next.t(reason)
        : content,
    reference: event.request_id || undefined,
  };
}
