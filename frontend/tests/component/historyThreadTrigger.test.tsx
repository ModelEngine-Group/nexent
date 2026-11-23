// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState, type ComponentProps } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { HistoryThreadTrigger } from "@/app/newchat/assistant-ui/history-thread-trigger";

const state = vi.hoisted(() => ({
  threadListItem: { id: "saved-thread", custom: { agentId: 7 as unknown } },
  overrides: {} as Record<string, number>,
  switchTo: vi.fn(),
}));
vi.mock("@assistant-ui/react", () => ({
  useAuiState: (select: (value: unknown) => unknown) =>
    select({ ...state, threads: { threadItems: [state.threadListItem] } }),
  ThreadListItemPrimitive: {
    Trigger: ({ onClick, ...props }: ComponentProps<"button">) => (
      <button
        {...props}
        onClick={(event) => {
          onClick?.(event);
          if (!event.defaultPrevented) state.switchTo();
        }}
      />
    ),
  },
}));
vi.mock("@/app/newchat/adapter/thread-agent-registry", async (load) => ({
  ...(await load<object>()),
  useThreadAgentOverrides: () => state.overrides,
}));

beforeEach(() => {
  state.threadListItem.custom.agentId = 7;
  state.overrides = {};
  state.switchTo.mockClear();
});

test("reopens the same saved thread after returning to discovery repeatedly", () => {
  function Harness() {
    const [agent, selectAgent] = useState<number | null>(null);
    return (
      <>
        <span>{agent === null ? "discovery" : `agent-${agent}`}</span>
        <button onClick={() => selectAgent(null)}>Back</button>
        <HistoryThreadTrigger onAgentSelected={selectAgent}>
          History
        </HistoryThreadTrigger>
      </>
    );
  }
  render(<Harness />);
  for (let attempt = 0; attempt < 3; attempt++) {
    fireEvent.click(screen.getByText("History"));
    expect(screen.getByText("agent-7")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Back"));
    expect(screen.getByText("discovery")).toBeInTheDocument();
  }
  expect(state.switchTo).toHaveBeenCalledTimes(3);
});

test("uses the thread override when metadata is absent", () => {
  state.threadListItem.custom.agentId = undefined;
  state.overrides = { "saved-thread": 9 };
  const select = vi.fn();
  render(
    <>
      <HistoryThreadTrigger onAgentSelected={select}>
        History
      </HistoryThreadTrigger>
    </>
  );
  fireEvent.click(screen.getByText("History"));
  expect(select).toHaveBeenCalledWith(9);
});

test("does not select an unrelated agent for invalid metadata", () => {
  state.threadListItem.custom.agentId = "invalid";
  const select = vi.fn();
  render(
    <>
      <HistoryThreadTrigger onAgentSelected={select}>
        History
      </HistoryThreadTrigger>
    </>
  );
  fireEvent.click(screen.getByText("History"));
  expect(select).not.toHaveBeenCalled();
  expect(state.switchTo).toHaveBeenCalledOnce();
});

test("preserves cancelled activation", () => {
  render(
    <HistoryThreadTrigger onClick={(event) => event.preventDefault()}>
      History
    </HistoryThreadTrigger>
  );
  fireEvent.click(screen.getByText("History"));
  expect(state.switchTo).not.toHaveBeenCalled();
});

test("retains ordinary thread switching without an Agent callback", () => {
  render(<HistoryThreadTrigger>History</HistoryThreadTrigger>);
  fireEvent.click(screen.getByText("History"));
  expect(state.switchTo).toHaveBeenCalledOnce();
});
