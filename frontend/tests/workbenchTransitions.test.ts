import assert from "node:assert/strict";
import test from "node:test";
import type { AssistantRuntime } from "@assistant-ui/react";
import {
  changeAgentTopology,
  changeCreationThread,
  // @ts-expect-error -- Node's TypeScript runner requires an explicit extension.
} from "../features/workbench/conversationTransitions.ts";

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
      switchToNewThread: async () => {
        events.push("new-thread");
      },
    },
  } as unknown as AssistantRuntime;
  return { runtime, events, attachment };
}

test("UT-FE-WB-011 returning from creation opens one generic thread without copying its draft", async () => {
  const { runtime, events } = fixture({ messages: 0 });
  const originalDraft = runtime.thread.composer.getState();
  await changeCreationThread(runtime, () => {
    events.push("generic_chat");
  });
  assert.deepEqual(events, ["new-thread", "generic_chat"]);
  assert.deepEqual(runtime.thread.composer.getState(), originalDraft);
});

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

test("UT-FE-WB-030 Agent change after messages creates one preserved thread", async () => {
  const { runtime, events, attachment } = fixture();
  await changeAgentTopology(runtime, () => {
    events.push("apply");
  });
  assert.deepEqual(events, [
    "new-thread",
    "apply",
    ["text", "unsent draft"],
    ["attachment", attachment],
  ]);
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

test("A failed topology application still restores the unsent input", async () => {
  const { runtime, events, attachment } = fixture();
  await assert.rejects(
    changeAgentTopology(runtime, () => {
      throw new Error("preview failed");
    }),
    /preview failed/
  );
  assert.deepEqual(events, [
    "new-thread",
    ["text", "unsent draft"],
    ["attachment", attachment],
  ]);
  await changeAgentTopology(runtime, () => {});
});

test("Overlapping changes cannot create multiple new threads", async () => {
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
  assert.equal(events.filter((event) => event === "new-thread").length, 1);
});
