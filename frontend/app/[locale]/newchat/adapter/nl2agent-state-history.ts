// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { Nl2AgentStateEvent } from "./remote-chat-model-adapter";

/** Store only already-validated server facts; keep the latest count per stage. */
export function recordNl2AgentState(
  previous: readonly Nl2AgentStateEvent[],
  event: Nl2AgentStateEvent
): Nl2AgentStateEvent[] {
  if (event.event === "resource_retrieval_progress") {
    if (
      previous.some(
        (item) =>
          item.event === event.event &&
          item.run_id === event.run_id &&
          item.sequence >= event.sequence
      )
    )
      return [...previous];
    return [
      ...previous.filter(
        (item) =>
          item.event !== event.event ||
          (item.run_id === event.run_id && item.stage !== event.stage)
      ),
      event,
    ].slice(-32);
  }
  return [
    ...previous.filter(
      (item) => JSON.stringify(item) !== JSON.stringify(event)
    ),
    event,
  ].slice(-32);
}
