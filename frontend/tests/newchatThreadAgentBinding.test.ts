import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../app/[locale]/newchat/page.tsx", import.meta.url);
const adapterPath = new URL(
  "../app/[locale]/newchat/adapter/conversation-thread-list-adapter.tsx",
  import.meta.url
);
const threadPath = new URL(
  "../app/[locale]/newchat/assistant-ui/thread.tsx",
  import.meta.url
);

test("binds an agent selected for a new thread to that thread's metadata", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(
    page,
    /thread\.updateCustom\(\{\s*agentId:\s*agent\.id\s*\}\)/
  );
});

test("initializes a new thread before storing its selected agent", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(
    page,
    /const thread = runtime\.threads\.getItemById\([\s\S]*await thread\.initialize\(\);[\s\S]*await thread\.updateCustom\(/
  );
});

test("supports storing an agent on a new thread before the conversation exists on the server", async () => {
  const adapter = await readFile(adapterPath, "utf8");

  assert.match(
    adapter,
    /async updateCustom\(\s*_remoteId: string,\s*_custom: Record<string, unknown> \| undefined\s*\): Promise<void>/
  );
});

test("shows the selected agent name beneath a populated conversation title", async () => {
  const thread = await readFile(threadPath, "utf8");

  assert.match(
    thread,
    /\{hasMessages && variant !== "embedded" && \(\s*<span className="text-xs text-muted-foreground">\s*\{displayName\}/
  );
});
