import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAgentShareUrl,
  buildAgentUsageGuidePath,
  buildNorthboundDocsUrl,
  buildNorthboundCurl,
  buildNorthboundRunUrl,
  buildUserApiKeyPath,
  clearAgentUsageGuidePath,
  parseAgentUsageGuideParams,
  isAgentSharePath,
  isAnonymousConversationSharePath,
  // @ts-ignore -- Node's built-in TypeScript runner needs the extension.
} from "../lib/agentUsageGuide.ts";

test("builds the published Agent repository guide URL", () => {
  assert.equal(
    buildAgentUsageGuidePath("zh", 41),
    "/zh/agent-space?tab=mine&agent_id=41&guide=usage"
  );
});

test("requires login only for interactive Agent share links", () => {
  assert.equal(isAgentSharePath("/share/agent/signed-token"), true);
  assert.equal(isAgentSharePath("/share/agent/"), false);
  assert.equal(isAnonymousConversationSharePath("/share/snapshot-id"), true);
  assert.equal(
    isAnonymousConversationSharePath("/share/agent/signed-token"),
    false
  );
});

test("parses and clears one-time Agent usage guide URL state", () => {
  assert.deepEqual(
    parseAgentUsageGuideParams(
      new URLSearchParams("tab=mine&agent_id=41&guide=usage")
    ),
    { agentId: 41 }
  );
  assert.equal(
    parseAgentUsageGuideParams(new URLSearchParams("agent_id=41")),
    null
  );
  assert.equal(
    parseAgentUsageGuideParams(
      new URLSearchParams("agent_id=nope&guide=usage")
    ),
    null
  );
  assert.equal(
    clearAgentUsageGuidePath("zh", 41),
    "/zh/agent-space?tab=mine&agent_id=41"
  );
});

test("builds safe share and northbound API examples", () => {
  assert.equal(
    buildAgentShareUrl("https://nexent.example/", "zh", "share-token"),
    "https://nexent.example/zh/share/agent/share-token"
  );
  assert.equal(
    buildNorthboundRunUrl("https://api.example.com/root/"),
    "https://api.example.com/root/nb/v1/chat/run"
  );
  assert.equal(
    buildNorthboundRunUrl(undefined),
    "<NEXENT_BASE_URL>/nb/v1/chat/run"
  );
  assert.match(
    buildNorthboundCurl("demo-agent", "https://api.example.com/nb/v1/chat/run"),
    /<YOUR_API_KEY>/
  );
  assert.match(
    buildNorthboundCurl("demo-agent", "https://api.example.com/nb/v1/chat/run"),
    /demo-agent/
  );
  assert.equal(buildUserApiKeyPath("zh"), "/zh/users");
  assert.equal(
    buildNorthboundDocsUrl("en"),
    "https://modelengine-group.github.io/nexent/en/integration/integration-out/northbound-api.html"
  );
});
