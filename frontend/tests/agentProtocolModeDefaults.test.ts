import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readFrontendFile = (path: string) =>
  readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("new and missing-policy agents default to legacy mode", async () => {
  const [configStore, agentStore, service, actions, policy] = await Promise.all(
    [
      readFrontendFile("stores/agentConfigStore.ts"),
      readFrontendFile("stores/agentStore.ts"),
      readFrontendFile("services/agentConfigService.ts"),
      readFrontendFile(
        "app/[locale]/agents/components/agent-config-actions.tsx"
      ),
      readFrontendFile("app/[locale]/agents/components/agent-run-policy.tsx"),
    ]
  );

  assert.match(configStore, /enable_protocol_repair_retry:\s*false/);
  for (const source of [configStore, agentStore, service, actions, policy]) {
    assert.doesNotMatch(source, /enable_protocol_repair_retry\s*\?\?\s*true/);
  }
  assert.match(
    policy,
    /checked=\{editedAgent\.enable_protocol_repair_retry \?\? false\}/
  );
});

test("the policy descriptions distinguish legacy and strict modes", async () => {
  const [english, chinese] = await Promise.all([
    readFrontendFile("public/locales/en/common.json"),
    readFrontendFile("public/locales/zh/common.json"),
  ]);
  const en = JSON.parse(english);
  const zh = JSON.parse(chinese);

  assert.match(
    en["agent.runPolicy.protocolRepairRetryHint"],
    /Off by default.*legacy Agent flow/
  );
  assert.match(
    en["agent.runPolicy.protocolRepairRetryHint"],
    /On: enforce the strict action format/
  );
  assert.match(
    zh["agent.runPolicy.protocolRepairRetryHint"],
    /默认关闭.*旧版智能体流程/
  );
  assert.match(
    zh["agent.runPolicy.protocolRepairRetryHint"],
    /开启：严格校验动作格式/
  );
});
