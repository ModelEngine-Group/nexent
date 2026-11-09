// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import type { ApiConversationDetail } from "@/types/conversation";

async function restore(
  units: Array<{ type: string; content: string }>,
  standalone = false
) {
  const detail = {
    conversation_id: "42",
    conversation_title: "智能客服助手",
    agent_id: 77,
    target: { type: "agent", id: 17 },
    agent_system_key: "nl2agent_main",
    workbench_config: standalone ? null : { mode: "agent_create" },
    message: [{ role: "assistant", message_id: 5, message: units }],
  } as ApiConversationDetail;
  const adapter = new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42", externalId: "42" }),
    async () => detail
  );
  return adapter.load();
}

it("restores a completed Agent card in the historical assistant message", async () => {
  const history = await restore([
    {
      type: "nl2a_state",
      content: JSON.stringify({
        event: "agent_generation_completed",
        agent_id: 17,
      }),
    },
    { type: "final_answer", content: "智能体已完成生成。" },
  ]);
  expect(history.messages).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        message: expect.objectContaining({
          role: "assistant",
          content: expect.arrayContaining([
            expect.objectContaining({
              type: "data",
              name: "nl2agent-created",
              data: { agentId: 17, completed: true },
            }),
          ]),
        }),
      }),
    ])
  );
});

it("does not turn an answer into a completed or saved result card", async () => {
  const history = await restore([
    { type: "final_answer", content: "草稿已保存。" },
  ]);
  const content = history.messages.find(
    (item) => item.message.role === "assistant"
  )?.message.content;
  expect(
    content?.some(
      (part) => part.type === "data" && part.name === "nl2agent-created"
    )
  ).toBe(false);
  expect(
    content?.some(
      (part) => part.type === "text" && part.text.includes("草稿已保存")
    )
  ).toBe(true);
});

it("does not infer standalone completion from executor identity and target", async () => {
  const history = await restore(
    [{ type: "final_answer", content: "Draft saved" }],
    true
  );
  const parts = history.messages.find(
    (item) => item.message.role === "assistant"
  )?.message.content;
  expect(
    parts?.some(
      (part) => part.type === "data" && part.name === "nl2agent-created"
    )
  ).toBe(false);
});

it("rejects a mismatched completion and deduplicates matching events", async () => {
  const state = (id: number) => ({
    type: "nl2a_state",
    content: JSON.stringify({
      event: "agent_generation_completed",
      agent_id: id,
    }),
  });
  const history = await restore([state(99), state(17), state(17)]);
  const content = history.messages.find(
    (item) => item.message.role === "assistant"
  )?.message.content;
  expect(
    content?.filter(
      (part) => part.type === "data" && part.name === "nl2agent-created"
    )
  ).toEqual([
    {
      type: "data",
      name: "nl2agent-created",
      data: { agentId: 17, completed: true },
    },
  ]);
});

it.each(["smolagents", "jiuwen"])(
  "%s history waits for an explicit completion event",
  async (core) => {
    const ending =
      core === "jiuwen"
        ? {
            type: "run_terminal",
            content: JSON.stringify({
              type: "run_terminal",
              schema_version: 1,
              runtime_mode: "native_agent",
              agent_core: "jiuwen",
              turn_id: "history-turn",
              sequence: 1,
              content: "",
              status: "completed",
              end_reason: "awaiting_input",
              final_content: "",
              final_block_ids: [],
              error: null,
            }),
          }
        : { type: "final_answer", content: "" };
    for (const completed of [false, true]) {
      const history = await restore([
        ...(completed
          ? [
              {
                type: "nl2a_state",
                content: JSON.stringify({
                  event: "agent_generation_completed",
                  agent_id: 17,
                }),
              },
            ]
          : []),
        ending,
      ]);
      const parts = history.messages.find(
        (item) => item.message.role === "assistant"
      )?.message.content;
      expect(
        (parts ?? []).filter(
          (part) => part.type === "data" && part.name === "nl2agent-created"
        )
      ).toEqual(
        completed
          ? [
              {
                type: "data",
                name: "nl2agent-created",
                data: { agentId: 17, completed: true },
              },
            ]
          : []
      );
    }
  }
);
