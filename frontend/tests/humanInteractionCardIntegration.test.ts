import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path: string) => readFile(new URL(path, import.meta.url), "utf8");

test("nl2agent and runtime HITL share the clarification card", async () => {
  const [nl2agentCard, hitlCards] = await Promise.all([
    read("../app/[locale]/newchat/ui/requirement-clarification-card.tsx"),
    read("../features/humanInteraction/HumanInteractionCards.tsx"),
  ]);

  assert.match(nl2agentCard, /components\/interaction\/clarification-card/);
  assert.match(hitlCards, /components\/interaction\/clarification-card/);
  assert.match(hitlCards, /export function HumanInteractionCards/);
  assert.match(hitlCards, /item\.kind === "ACTION_APPROVAL"/);
  assert.match(hitlCards, /"澄清需求"/);
});

test("runtime HITL cards remain in the thread while steering moves to the composer", async () => {
  const [page, chat, thread, composer] = await Promise.all([
    read("../app/[locale]/newchat/page.tsx"),
    read("../app/[locale]/newchat/assistant-ui/chat.tsx"),
    read("../app/[locale]/newchat/assistant-ui/thread.tsx"),
    read("../app/[locale]/newchat/assistant-ui/composer.tsx"),
  ]);

  assert.doesNotMatch(page, /HumanInteractionControls/);
  assert.match(page, /RunMessageQueueContext.Provider/);
  assert.match(page, /<HumanInteractionCards controller={hitlController}/);

  assert.match(chat, /interactionContent={interactionContent}/);
  assert.match(thread, /{interactionContent}/);
  assert.match(thread, /disabled={readOnly}/);
  assert.match(composer, /<QueuedRunMessageStrip/);
  assert.match(composer, /disabled={queueLocked}/);
});

test("a decided request reconnects a detached HITL stream", async () => {
  const controller = await read(
    "../features/humanInteraction/useHumanInteractionController.ts"
  );

  assert.match(controller, /\[isRunning, onContinue, refresh, run\?\.status\]/);
  assert.match(
    controller,
    /STREAM_RECONNECT_STATUSES\.has\(latestRun\.status\)/
  );
  assert.match(
    controller,
    /onContinue\(pendingResume\.runId, pendingResume\.after\)/
  );
});

test("normal chat enables proactive clarification when the runtime supports it", async () => {
  const [controller, adapter, server] = await Promise.all([
    read("../features/humanInteraction/useHumanInteractionController.ts"),
    read("../app/[locale]/newchat/adapter/remote-chat-model-adapter.ts"),
    read("../server.js"),
  ]);

  assert.match(
    controller,
    /value\.enabled && value\.accept_new_runs !== false/
  );
  assert.match(controller, /onEnabledChangeRef\.current\(true\)/);
  assert.match(adapter, /enable_hitl: !isEphemeralRuntime/);
  assert.match(server, /"\/api\/agent\/human-interactions"/);
});
