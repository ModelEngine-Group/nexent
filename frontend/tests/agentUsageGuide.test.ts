// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAgentShareUrl,
  buildCopyAriaLabel,
  buildNorthboundDocsUrl,
  buildNorthboundCurl,
  buildNorthboundRunUrl,
  buildUserApiKeyPath,
  getAgentUsageGuideAccess,
  getAgentPublishCompletion,
  getA2AGuideState,
  resolveAgentDeepLinkAction,
  buildDefaultAgentVersionName,
  isAnonymousConversationSharePath,
  // @ts-ignore -- Node's built-in TypeScript runner needs the extension.
} from "../lib/agentUsageGuide.ts";

test("completes ordinary and A2A publishes but keeps failed publishes in the editor", () => {
  assert.equal(getAgentPublishCompletion({ success: true }), "complete");
  assert.equal(
    getAgentPublishCompletion({
      success: true,
      data: { a2a_agent: { endpoint_id: "a2a-42" } },
    }),
    "complete"
  );
  assert.equal(getAgentPublishCompletion({ success: false }), "stay");
});

test("keeps conversation snapshot shares anonymous", () => {
  assert.equal(isAnonymousConversationSharePath("/share/snapshot-id"), true);
});

test("resolves an Agent chat deep link only once", () => {
  const agents = [{ id: 41 }, { id: 42 }];
  const getAgentId = (agent: { id: number }) => agent.id;

  assert.deepEqual(
    resolveAgentDeepLinkAction({
      agentId: 41,
      agents,
      consumed: false,
      isLoading: true,
      getAgentId,
    }),
    { action: "wait" }
  );
  assert.deepEqual(
    resolveAgentDeepLinkAction({
      agentId: 41,
      agents,
      consumed: false,
      isLoading: false,
      getAgentId,
    }),
    { action: "select", agent: { id: 41 } }
  );
  assert.deepEqual(
    resolveAgentDeepLinkAction({
      agentId: 41,
      agents,
      consumed: true,
      isLoading: false,
      getAgentId,
    }),
    { action: "ignore" }
  );
  assert.deepEqual(
    resolveAgentDeepLinkAction({
      agentId: 404,
      agents,
      consumed: false,
      isLoading: false,
      getAgentId,
    }),
    { action: "dismiss" }
  );
});

test("shows usage guidance only for published Agents and protects share management", () => {
  assert.deepEqual(
    getAgentUsageGuideAccess({ currentVersionNo: null, permission: "OWNER" }),
    { canOpen: false, canManageShare: true }
  );
  assert.deepEqual(
    getAgentUsageGuideAccess({
      currentVersionNo: 3,
      permission: "READ_ONLY",
    }),
    { canOpen: true, canManageShare: false }
  );
});

test("builds safe share and northbound API examples", () => {
  assert.equal(
    buildAgentShareUrl("https://nexent.example/", "zh", 41),
    "https://nexent.example/zh/newchat?agent_id=41"
  );
  assert.equal(
    buildNorthboundRunUrl("https://api.example.com/root/"),
    "https://api.example.com/root/nb/v1/chat/run"
  );
  assert.equal(
    buildNorthboundRunUrl(),
    "http://localhost:5013/api/nb/v1/chat/run"
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

test("northbound examples preserve the public API prefix and normalize empty configuration", () => {
  assert.equal(
    buildNorthboundRunUrl(" https://api.example.com/api/// "),
    "https://api.example.com/api/nb/v1/chat/run"
  );
  for (const value of [undefined, "", "   "]) {
    assert.equal(
      buildNorthboundRunUrl(value),
      "http://localhost:5013/api/nb/v1/chat/run"
    );
  }
});

test("builds an editable default Agent version name from name and timestamp", () => {
  assert.equal(
    buildDefaultAgentVersionName(" Medic_2 ", new Date(2026, 8, 22, 9, 5)),
    "Medic_2-2609220905"
  );
  assert.equal(
    buildDefaultAgentVersionName(null, new Date(2026, 8, 22, 9, 5)),
    "2609220905"
  );
});

test("builds a descriptive accessible name for icon-only copy actions", () => {
  assert.equal(
    buildCopyAriaLabel("Copy", "Agent Card URL"),
    "Copy Agent Card URL"
  );
});

test("keeps A2A loading, error, disabled, and enabled states distinct", () => {
  assert.equal(
    getA2AGuideState({ isLoading: true, isError: false, isEnabled: false }),
    "loading"
  );
  assert.equal(
    getA2AGuideState({ isLoading: false, isError: true, isEnabled: false }),
    "error"
  );
  assert.equal(
    getA2AGuideState({ isLoading: false, isError: false, isEnabled: false }),
    "disabled"
  );
  assert.equal(
    getA2AGuideState({ isLoading: false, isError: false, isEnabled: true }),
    "enabled"
  );
});
