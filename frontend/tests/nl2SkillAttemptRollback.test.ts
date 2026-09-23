import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path: string) => readFile(new URL(path, import.meta.url), "utf8");

test("NL2Skill rolls rejected model attempts out of both chat and draft UI", async () => {
  const [adapter, modal] = await Promise.all([
    read("../app/[locale]/newchat/adapter/remote-chat-model-adapter.ts"),
    read("../app/[locale]/agents/components/agentConfig/SkillBuildModal.tsx"),
  ]);

  assert.match(adapter, /beginNl2SkillAttempt\(chunk\.attempt_id\)/);
  assert.match(
    adapter,
    /resolveNl2SkillAttempt\(chunk\.attempt_id, "rollback"\)/
  );
  assert.match(adapter, /custom\?\.onNl2SkillEvent\?\.\(chunk\)/);
  assert.match(modal, /event\.type === "model_attempt_control"/);
  assert.match(modal, /event\.phase === "rollback"/);
  assert.match(modal, /rollbackDraftStream\(\)/);
  assert.doesNotMatch(
    modal,
    /event\.type === "model_attempt_control"[\s\S]{0,160}message\.error/
  );
});
