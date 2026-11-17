// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMemo } from "react";
import { useConfig } from "@/hooks/useConfig";
import { useModelList } from "@/hooks/model/useModelList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import type { Agent } from "@/types/agentConfig";
import { deriveModelOptions } from "./modelOptions";
import { useConversationModelControls } from "./useConversationModelControls";

export function useCreatorModelControls(
  agent: Agent,
  sessionId: string,
  permission: "agent:create" | "skill:create"
) {
  const { models } = useModelList();
  const { defaultLlmModelConfig } = useConfig();
  const { user, hasPermission } = useAuthorizationContext();
  const options = useMemo(
    () => deriveModelOptions(agent, models, "tenant"),
    [agent, models]
  );
  const controls = useConversationModelControls(
    options,
    `${user?.tenantId ?? ""}:${user?.id ?? ""}:${sessionId}`,
    defaultLlmModelConfig?.id?.toString()
  );
  return {
    ...controls,
    canCreate: hasPermission(permission),
    canSend: hasPermission(permission) && controls.canSend,
  };
}
