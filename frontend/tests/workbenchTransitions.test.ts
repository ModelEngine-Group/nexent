// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test, { before } from "node:test";
import i18n from "i18next";
import type { AssistantRuntime } from "@assistant-ui/react";
import {
  changeAgentTopology,
  changeCreationThread,
  returnFromCreation,
  startWorkbenchConversation,
  // @ts-expect-error -- Node's TypeScript runner requires an explicit extension.
} from "../features/workbench/conversationTransitions.ts";

before(async () => {
  await i18n.init({
    lng: "zh",
    keySeparator: false,
    resources: {
      zh: {
        translation: JSON.parse(
          readFileSync(
            new URL("../public/locales/zh/common.json", import.meta.url),
            "utf8"
          )
        ),
      },
    },
  });
});

function fixture({ messages = 1, running = false, uploading = false } = {}) {
  const events: unknown[] = [];
  const attachment = {
    id: "attachment-1",
    type: "file",
    name: "invoice.pdf",
    status: { type: uploading ? "running" : "complete" },
    content: [],
  };
  const runtime = {
    thread: {
      getState: () => ({
        messages: Array(messages).fill({}),
        isRunning: running,
      }),
      composer: {
        getState: () => ({ text: "unsent draft", attachments: [attachment] }),
        setText: (text: string) => events.push(["text", text]),
        addAttachment: async (value: unknown) => {
          events.push(["attachment", value]);
        },
      },
    },
    threads: {
      getState: () => ({ mainThreadId: "ordinary", newThreadId: undefined }),
      getItemById: () => ({
        initialize: async () => events.push("reserve-draft"),
      }),
      switchToThread: async (id: string) => {
        events.push(["restore-thread", id]);
      },
      switchToNewThread: async () => {
        events.push("new-thread");
      },
    },
  } as unknown as AssistantRuntime;
  return { runtime, events, attachment };
}

for (const running of [false, true]) {
  test(`a new conversation reserves its unsent draft while running=${running}`, async () => {
    const { runtime, events } = fixture({ messages: 0, running });
    runtime.threads.getState = () =>
      ({ mainThreadId: "creation", newThreadId: "creation" }) as ReturnType<
        typeof runtime.threads.getState
      >;
    const original = runtime.thread.composer.getState();
    await startWorkbenchConversation(runtime, () =>
      events.push("generic_chat")
    );
    assert.deepEqual(events, ["reserve-draft", "new-thread", "generic_chat"]);
    assert.deepEqual(runtime.thread.composer.getState(), original);
  });
}

test("a failed new conversation does not reset the source and releases its transition lock", async () => {
  const { runtime, events } = fixture();
  runtime.threads.switchToNewThread = async () => {
    throw new Error("switch failed");
  };
  await assert.rejects(
    startWorkbenchConversation(runtime, () => events.push("reset")),
    /switch failed/
  );
  assert.equal(events.length, 0);
  runtime.threads.switchToNewThread = async () => {};
  await startWorkbenchConversation(runtime, () => events.push("reset"));
  assert.deepEqual(events, ["reset"]);
});

test("new conversation and creation actions cannot overlap", async () => {
  const { runtime, events } = fixture();
  let release!: () => void;
  runtime.threads.switchToNewThread = () =>
    new Promise<void>((resolve) => {
      release = resolve;
    });
  const first = startWorkbenchConversation(runtime, () => events.push("reset"));
  await assert.rejects(startWorkbenchConversation(runtime, () => {}));
  await assert.rejects(changeCreationThread(runtime, () => {}));
  release();
  await first;
  assert.deepEqual(events, ["reset"]);
});

test("UT-FE-WB-011 returning from creation opens one generic thread without copying its draft", async () => {
  const { runtime, events } = fixture({ messages: 0 });
  const originalDraft = runtime.thread.composer.getState();
  await changeCreationThread(runtime, () => {
    events.push("generic_chat");
  });
  assert.deepEqual(events, ["new-thread", "generic_chat"]);
  assert.deepEqual(runtime.thread.composer.getState(), originalDraft);
});

test("an unsent ordinary draft is reserved before starting a separate creation thread", async () => {
  const { runtime, events } = fixture({ messages: 0 });
  runtime.threads.getState = () =>
    ({ mainThreadId: "ordinary", newThreadId: "ordinary" }) as ReturnType<
      typeof runtime.threads.getState
    >;
  await changeCreationThread(runtime, () => events.push("agent_create"));
  assert.deepEqual(events, ["reserve-draft", "new-thread", "agent_create"]);
  await returnFromCreation(runtime, "ordinary", () =>
    events.push("restore-config")
  );
  assert.deepEqual(events.slice(-2), [
    ["restore-thread", "ordinary"],
    "restore-config",
  ]);
});

for (const options of [{ running: true }, { uploading: true }]) {
  test(`creation and return reject an active run or upload: ${JSON.stringify(options)}`, async () => {
    const { runtime, events } = fixture(options);
    await assert.rejects(
      changeCreationThread(runtime, () => events.push("unexpected"))
    );
    await assert.rejects(
      returnFromCreation(runtime, "ordinary", () => events.push("unexpected"))
    );
    assert.deepEqual(events, []);
  });
}

test("creation transition rejects overlaps and releases its lock after failure", async () => {
  const { runtime, events } = fixture();
  let reject!: (error: Error) => void;
  runtime.threads.switchToNewThread = () =>
    new Promise<void>((_, fail) => {
      reject = fail;
    });
  const first = changeCreationThread(runtime, () => events.push("unexpected"));
  await assert.rejects(
    changeCreationThread(runtime, () => {}),
    /正在切换/
  );
  reject(new Error("thread creation failed"));
  await assert.rejects(first, /thread creation failed/);
  assert.equal(events.length, 0);
  runtime.threads.switchToNewThread = async () => {};
  await changeCreationThread(runtime, () => events.push("retry"));
  assert.deepEqual(events, ["retry"]);
});

test("UT-FE-WB-031 Agent change in an empty conversation stays local", async () => {
  const { runtime, events } = fixture({ messages: 0 });
  await changeAgentTopology(runtime, () => {
    events.push("apply");
  });
  assert.deepEqual(events, ["apply"]);
});

test("UT-FE-WB-030 Agent change after messages stays in the same thread", async () => {
  const { runtime, events } = fixture();
  await changeAgentTopology(runtime, () => {
    events.push("apply");
  });
  assert.deepEqual(events, ["apply"]);
});

for (const options of [{ running: true }, { uploading: true }]) {
  test(`Agent change is rejected without mutation: ${JSON.stringify(options)}`, async () => {
    const { runtime, events } = fixture(options);
    await assert.rejects(
      changeAgentTopology(runtime, () => {
        events.push("apply");
      })
    );
    assert.deepEqual(events, []);
  });
}

test("A failed topology application leaves the unsent input untouched", async () => {
  const { runtime, events } = fixture();
  await assert.rejects(
    changeAgentTopology(runtime, () => {
      throw new Error("preview failed");
    }),
    /preview failed/
  );
  assert.deepEqual(events, []);
  await changeAgentTopology(runtime, () => {});
});

test("Overlapping changes cannot mutate the same conversation concurrently", async () => {
  const { runtime, events } = fixture();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const first = changeAgentTopology(runtime, () => gate);
  await assert.rejects(
    changeAgentTopology(runtime, () => {}),
    /正在切换/
  );
  release();
  await first;
  assert.equal(events.filter((event) => event === "new-thread").length, 0);
});
