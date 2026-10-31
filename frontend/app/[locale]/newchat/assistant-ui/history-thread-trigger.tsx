// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { type ComponentProps } from "react";
import { ThreadListItemPrimitive, useAuiState } from "@assistant-ui/react";
import {
  resolveThreadAgentId,
  useThreadAgentOverrides,
} from "../adapter/thread-agent-registry";

export function HistoryThreadTrigger({
  onAgentSelected,
  ...props
}: ComponentProps<typeof ThreadListItemPrimitive.Trigger> & {
  onAgentSelected?: (agentId: number) => void;
}) {
  const thread = useAuiState((state) => state.threadListItem);
  const metadataAgentId = useAuiState(
    (state) =>
      state.threads.threadItems.find((item) => item.id === thread.id)?.custom
        ?.agentId
  );
  const overrides = useThreadAgentOverrides();
  return (
    <ThreadListItemPrimitive.Trigger
      {...props}
      onClick={(event) => {
        props.onClick?.(event);
        if (event.defaultPrevented) return;
        const agentId = resolveThreadAgentId(
          metadataAgentId,
          overrides[thread.id]
        );
        if (agentId !== null) onAgentSelected?.(agentId);
      }}
    />
  );
}
