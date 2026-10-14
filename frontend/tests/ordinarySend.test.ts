import assert from "node:assert/strict";
import test from "node:test";
import {
  ordinarySendError,
  protectOrdinarySend,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../app/[locale]/newchat/utils/ordinary-send.ts";

function fixture() {
  let running = false;
  let text = "Original draft";
  let snapshot = "before";
  const subscribers = new Set<() => void>();
  const attachment = { id: "file-1", name: "report.csv", content: [] };
  let attachments = [attachment];
  const thread = {
    export: () => snapshot,
    import: (value: string) => {
      snapshot = value;
    },
    getState: () => ({ isRunning: running }),
    subscribe: (listener: () => void) => {
      subscribers.add(listener);
      return () => subscribers.delete(listener);
    },
    composer: {
      getState: () => ({ text, attachments }),
      setText: (value: string) => {
        text = value;
      },
      addAttachment: (value: typeof attachment) => {
        attachments = [...attachments, value];
      },
    },
  };
  return {
    thread,
    snapshot: () => snapshot,
    subscribers,
    start: () => {
      running = true;
      snapshot = "optimistic";
      text = "";
      attachments = [];
    },
    settle: () => {
      running = false;
      for (const listener of [...subscribers]) listener();
    },
  };
}

test("a rejected ordinary send restores messages, draft and attachments only after settling", () => {
  const f = fixture();
  const errors: unknown[] = [];
  const callbacks = protectOrdinarySend(f.thread as never, {
    restoreDraft: true,
    onRejected: (error) => errors.push(error),
  });
  f.start();
  f.thread.composer.setText("New typing");
  callbacks.onRunRejected(new Error("agent_run_conflict"));
  assert.equal(f.snapshot(), "optimistic");
  assert.equal(errors.length, 0);
  f.settle();
  assert.equal(f.snapshot(), "before");
  assert.equal(
    f.thread.composer.getState().text,
    "Original draft\n\nNew typing"
  );
  assert.equal(f.thread.composer.getState().attachments[0].name, "report.csv");
  assert.equal(f.subscribers.size, 0);
  assert.equal(errors.length, 1);
  callbacks.onRunRejected(new Error("duplicate"));
  assert.equal(errors.length, 1);
});

test("an accepted send is never rolled back by a later stream failure", () => {
  const f = fixture();
  let started = 0;
  const callbacks = protectOrdinarySend(f.thread as never, {
    restoreDraft: true,
    onStarted: () => started++,
    onRejected: () => assert.fail("accepted"),
  });
  f.start();
  callbacks.onRunStarted();
  callbacks.onRunStarted();
  callbacks.onRunRejected(new Error("stream failed"));
  f.settle();
  assert.equal(started, 1);
  assert.equal(f.snapshot(), "optimistic");
});

test("a card rejection leaves the independent composer draft intact", () => {
  const f = fixture();
  const callbacks = protectOrdinarySend(f.thread as never, {
    restoreDraft: false,
    onRejected: () => {},
  });
  f.start();
  f.thread.composer.setText("Independent follow-up");
  callbacks.onRunRejected(new Error("full"));
  f.settle();
  assert.equal(f.thread.composer.getState().text, "Independent follow-up");
  assert.equal(f.snapshot(), "before");
  assert.match(
    ordinarySendError(new Error("agent_run_conflict"), "zh-CN"),
    /上一轮正在结束/
  );
});

test("ordinary send prefers a localized conversation limit message", () => {
  const error = {
    code: "120104",
    message:
      "Conversation turn limit reached: maximum 1 turns per conversation",
    details: { resource: "conversation_turns", limit: 1 },
  };
  const localized = ordinarySendError(error, "zh-CN", (value) =>
    (value as typeof error).details.resource === "conversation_turns"
      ? "当前会话对话轮数已达到上限：每个会话最多 1 轮"
      : null
  );

  assert.equal(localized, "当前会话对话轮数已达到上限：每个会话最多 1 轮");
});
