// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ApiConversationDetail } from "@/types/conversation";

/** Identify the executor independently of its edited resource or UI entrypoint. */
export function getCreatorMode(
  conversation: Pick<
    ApiConversationDetail,
    "agent_system_key" | "workbench_config"
  >
): "agent_create" | "skill_create" | undefined {
  if (conversation.agent_system_key === "nl2agent_main") return "agent_create";
  if (conversation.agent_system_key === "nl2skill_main") return "skill_create";
  const mode = conversation.workbench_config?.mode;
  return mode === "agent_create" || mode === "skill_create" ? mode : undefined;
}
