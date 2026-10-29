// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import type { ChatModelRunOptions } from "@assistant-ui/react";
import { ReadableStream } from "node:stream/web";
import {
  patchModelDraft,
  persistModelDrafts,
  readModelDraft,
  snapshotModelDrafts,
  acknowledgeModelDrafts,
} from "@/lib/conversationModelDrafts";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
const service = vi.hoisted(() => ({ create: vi.fn(), runAgent: vi.fn() }));
const api = vi.hoisted(() => ({
  getConversationModelPreferences: vi.fn(),
  patchConversationModelPreferences: vi.fn(),
}));
vi.mock("@/services/conversationService", () => ({
  conversationService: service,
}));
vi.mock("@/services/modelProfileService", () => api);
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));
beforeEach(() => {
  vi.resetAllMocks();
  api.getConversationModelPreferences.mockResolvedValue({ version: 4 });
  api.patchConversationModelPreferences.mockResolvedValue(undefined);
  service.runAgent.mockImplementation(async (_params, _signal, onIdentity) => {
    onIdentity?.("29");
    return new ReadableStream<Uint8Array>({
      start(controller) {
        controller.close();
      },
    }).getReader();
  });
});
async function run(scope: string, custom: Record<string, unknown> = {}) {
  const input = {
    messages: [
      { id: "q", role: "user", content: [{ type: "text", text: "hello" }] },
    ],
    abortSignal: new AbortController().signal,
    context: { config: { modelName: "42" } },
    runConfig: { custom },
    unstable_threadId: scope,
  } as unknown as ChatModelRunOptions;
  const result = remoteChatModelAdapter.run(input);
  if (Symbol.asyncIterator in result)
    for await (const chunk of result) {
      void chunk;
    }
  else await result;
}
it.each([false, true])(
  "SU-AC-02 sends and acknowledges identical first-turn preferences with Workbench=%s",
  async (workbench) => {
    const scope = `first-${workbench}`;
    const values = { temperature: 0, top_p: 0.81, enable_thinking: true };
    patchModelDraft(scope, 42, values, []);
    await run("adapter-thread", {
      agentId: 7,
      modelPreferenceScope: scope,
      ...(workbench
        ? {
            workbenchConfig: {
              schema_version: 4,
              mode: "generic_chat",
              agent_mounts: [],
              skill_mounts: [],
            },
            workbenchConfigVersion: 0,
          }
        : {}),
    });
    expect(service.create).not.toHaveBeenCalled();
    expect(api.patchConversationModelPreferences).not.toHaveBeenCalled();
    const request = service.runAgent.mock.calls[0][0];
    expect(request.model_parameter_preferences).toEqual({ "42": values });
    expect(request.conversation_id).toBeUndefined();
    expect(request.entrypoint).toBe(workbench ? "workbench" : undefined);
    expect(request).not.toHaveProperty("generation_config");
    expect(readModelDraft(scope, 42)).toEqual({});
  }
);
it("SU-AC-02 preserves first-turn choices after a rejected run, without creating an orphan ordinary conversation", async () => {
  patchModelDraft("failed-first", 42, { temperature: 0.19 }, []);
  service.runAgent.mockRejectedValueOnce(new Error("invalid preferences"));
  await expect(run("failed-first")).rejects.toThrow("invalid preferences");
  expect(readModelDraft("failed-first", 42)).toEqual({ temperature: 0.19 });
  expect(service.create).not.toHaveBeenCalled();
  await run("failed-first");
  expect(readModelDraft("failed-first", 42)).toEqual({});
});
it("SU-AC-05 blocks an existing conversation run after failed CAS and retains the draft", async () => {
  patchModelDraft("existing-failed", 42, { temperature: 0.3 }, []);
  api.patchConversationModelPreferences.mockRejectedValueOnce(
    new Error("conflict")
  );
  await expect(run("existing-failed", { threadId: "31" })).rejects.toThrow(
    "conflict"
  );
  expect(service.runAgent).not.toHaveBeenCalled();
  expect(readModelDraft("existing-failed", 42)).toEqual({ temperature: 0.3 });
});
it.each([false, true])(
  "SU-AC-01 persists existing conversation drafts through the shared CAS endpoint with Workbench=%s",
  async (workbench) => {
    const scope = `existing-${workbench}`;
    patchModelDraft(scope, 42, { temperature: 0.41 }, []);
    await run(scope, {
      threadId: "31",
      ...(workbench
        ? {
            workbenchConfig: {
              schema_version: 4,
              mode: "generic_chat",
              agent_mounts: [],
              skill_mounts: [],
            },
          }
        : {}),
    });
    expect(api.patchConversationModelPreferences).toHaveBeenCalledWith(31, 42, {
      expected_version: 4,
      parameter_values: { temperature: 0.41 },
      delete_parameters: [],
    });
    expect(
      service.runAgent.mock.calls[0][0].model_parameter_preferences
    ).toBeUndefined();
    expect(service.create).not.toHaveBeenCalled();
  }
);
it("SU-AC-04 isolates models and threads and preserves edits made while a frozen draft is in flight", () => {
  patchModelDraft("concurrent", 42, { temperature: 0.2, top_p: 0 }, []);
  patchModelDraft("concurrent", 43, { enable_thinking: false }, []);
  patchModelDraft("other", 42, { temperature: 0.9 }, []);
  const sent = snapshotModelDrafts("concurrent");
  patchModelDraft("concurrent", 42, { temperature: 0.4 }, []);
  acknowledgeModelDrafts("concurrent", sent);
  expect(readModelDraft("concurrent", 42)).toEqual({ temperature: 0.4 });
  expect(readModelDraft("concurrent", 43)).toEqual({});
  expect(readModelDraft("other", 42)).toEqual({ temperature: 0.9 });
  expect(sent["42"]).toEqual({ temperature: 0.2, top_p: 0 });
});
it("does not persist untouched drafts or create any conversation from the draft utility", async () => {
  patchModelDraft("deleted", 42, { top_p: 0.8 }, []);
  patchModelDraft("deleted", 42, {}, ["top_p"]);
  expect(await persistModelDrafts("deleted")).toBeUndefined();
  expect(service.create).not.toHaveBeenCalled();
  expect(api.patchConversationModelPreferences).not.toHaveBeenCalled();
});
