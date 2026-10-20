// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import type {
  ChatModelRunOptions,
  ChatModelRunResult,
} from "@assistant-ui/react";
import { ReadableStream } from "node:stream/web";

const runAgent = vi.hoisted(() => vi.fn());
vi.mock("@/services/conversationService", () => ({
  conversationService: { runAgent },
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import {
  applySkillCreationEvent,
  buildSkillSavePayload,
  initialSkillCreationDraft,
  type SkillCreationDraft,
  type SkillCreationEvent,
} from "@/features/workbench/creationRuntime";

async function renderSkillStream(
  events: SkillCreationEvent[],
  onNl2SkillEvent?: (event: SkillCreationEvent) => void,
  messages?: unknown[]
) {
  runAgent.mockImplementationOnce(async () =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const event of events) {
          controller.enqueue(
            new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`)
          );
        }
        controller.close();
      },
    }).getReader()
  );
  const input = {
    messages: messages ?? [
      {
        id: "question",
        role: "user",
        content: [{ type: "text", text: "创建合同审查技能" }],
      },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    runConfig: { custom: { runtimeMode: "nl2skill", onNl2SkillEvent } },
    unstable_threadId: "local-skill",
  } as unknown as ChatModelRunOptions;
  const run = remoteChatModelAdapter.run(input);
  const results: ChatModelRunResult[] = [];
  if (Symbol.asyncIterator in run) {
    for await (const result of run) results.push(result);
  } else {
    results.push(await run);
  }
  return results.at(-1)?.content ?? [];
}

it("does not create an empty Reasoning block for a Skill step marker", async () => {
  const content = await renderSkillStream([
    { type: "summary", content: "技能草稿已生成。" },
    { type: "step_count", content: "**步骤 1**" },
    { type: "done", content: "" },
  ]);
  expect(content.some((part) => part.type === "reasoning")).toBe(false);
});

it("saves only successful streamed files after rollback without mutating the prior draft", async () => {
  const previous = {
    ...initialSkillCreationDraft,
    files: { "SKILL.md": "previous", "scripts/keep.py": "keep" },
  };
  const snapshot = structuredClone(previous);
  let draft: SkillCreationDraft = previous;
  const content = await renderSkillStream(
    [
      { type: "agent_new_run", content: "" },
      { type: "model_attempt_control", phase: "begin", attempt_id: "a1" },
      { type: "skill_body", content: "FAILED", attempt_id: "a1" },
      {
        type: "file_content",
        path: "bad.py",
        content: "BAD",
        attempt_id: "a1",
      },
      { type: "summary", content: "Wrong summary", attempt_id: "a1" },
      { type: "model_attempt_control", phase: "rollback", attempt_id: "a1" },
      { type: "model_attempt_control", phase: "begin", attempt_id: "a2" },
      { type: "skill_body", content: "---\nname: demo\n", attempt_id: "a2" },
      {
        type: "skill_body",
        content: "description: Demo skill\ntags: [demo]\n---\n# Demo",
        attempt_id: "a2",
      },
      {
        type: "file_content",
        path: "run.py",
        content: "print('ok')",
        attempt_id: "a2",
      },
      { type: "summary", content: "Ready.", attempt_id: "a2" },
      { type: "model_attempt_control", phase: "commit", attempt_id: "a2" },
      { type: "done", content: "" },
    ],
    (event) => {
      draft = applySkillCreationEvent(draft, event);
    }
  );
  expect(buildSkillSavePayload(draft)).toEqual({
    name: "demo",
    description: "Demo skill",
    tags: ["demo"],
    source: "custom",
    content: "# Demo",
    files: [{ path: "run.py", content: "print('ok')" }],
  });
  expect(JSON.stringify(content)).not.toMatch(/FAILED|BAD|Wrong summary/);
  expect(content).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        type: "data",
        name: "nl2skill-file",
        data: expect.objectContaining({
          path: "run.py",
          content: "print('ok')",
          isStreaming: false,
        }),
      }),
    ])
  );
  expect(draft.checkpoints).toEqual({});
  expect(previous).toEqual(snapshot);
});

it("keeps existing files but prevents saving after a rolled-back failed stream", async () => {
  const previous = {
    ...initialSkillCreationDraft,
    files: { "SKILL.md": "---\nname: old\ndescription: Old\n---\nOld" },
  };
  let draft: SkillCreationDraft = previous;
  await renderSkillStream(
    [
      { type: "agent_new_run" },
      { type: "model_attempt_control", phase: "begin", attempt_id: "a1" },
      { type: "skill_body", content: "BAD", attempt_id: "a1" },
      { type: "model_attempt_control", phase: "rollback", attempt_id: "a1" },
      { type: "error", content: "NL2Skill execution failed." },
    ],
    (event) => {
      draft = applySkillCreationEvent(draft, event);
    }
  );
  expect(draft.files).toEqual(previous.files);
  expect(buildSkillSavePayload(draft)).toBeNull();
});

it("keeps real model thinking in a Skill creation stream", async () => {
  const content = await renderSkillStream([
    { type: "step_count", content: "**步骤 1**" },
    { type: "model_output_thinking", content: "先整理合同条款。" },
    { type: "summary", content: "技能草稿已生成。" },
    { type: "done", content: "" },
  ]);
  expect(content).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        type: "reasoning",
        text: "先整理合同条款。",
      }),
    ])
  );
});

it("sends the original request when continuing after an empty failed response", async () => {
  await renderSkillStream([{ type: "done", content: "" }], undefined, [
    {
      id: "original",
      role: "user",
      content: [{ type: "text", text: "创建会议纪要技能，支持导出 Markdown" }],
    },
    {
      id: "failed",
      role: "assistant",
      content: [],
      status: { type: "incomplete", reason: "error" },
    },
    {
      id: "continue",
      role: "user",
      content: [{ type: "text", text: "继续" }],
    },
  ]);
  const request = runAgent.mock.calls.at(-1)?.[0];
  expect(request.query).toBe("继续");
  expect(request.history).toEqual([
    { role: "user", content: "创建会议纪要技能，支持导出 Markdown" },
    { role: "assistant", content: "" },
  ]);
});
