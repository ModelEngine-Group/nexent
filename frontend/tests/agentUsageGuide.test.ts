import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAgentShareUrl,
  buildAuthenticationReturnPath,
  buildCopyAriaLabel,
  buildAgentUsageGuidePath,
  buildNorthboundDocsUrl,
  buildNorthboundCurl,
  buildNorthboundRunUrl,
  buildUserApiKeyPath,
  clearAgentUsageGuidePath,
  getAgentUsageGuideOpenAction,
  getAgentUsageGuideAccess,
  getAgentPublishCompletion,
  getA2AGuideState,
  reduceAgentShareGuideState,
  resolveAgentDeepLinkAction,
  resolveAgentUsageGuideTarget,
  parseAgentUsageGuideTargetParams,
  parseAgentUsageGuideParams,
  isAgentSharePath,
  isAnonymousConversationSharePath,
  // @ts-ignore -- Node's built-in TypeScript runner needs the extension.
} from "../lib/agentUsageGuide.ts";

test("builds the published Agent repository menu onboarding URL", () => {
  assert.equal(
    buildAgentUsageGuidePath("zh", 41),
    "/zh/agent-space?tab=mine&agent_id=41&onboarding=usage-menu"
  );
});

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

test("requires login only for interactive Agent share links", () => {
  assert.equal(isAgentSharePath("/share/agent/signed-token"), true);
  assert.equal(isAgentSharePath("/share/agent/"), false);
  assert.equal(isAnonymousConversationSharePath("/share/snapshot-id"), true);
  assert.equal(
    isAnonymousConversationSharePath("/share/agent/signed-token"),
    false
  );
});

test("preserves the complete localized Agent share return path", () => {
  assert.equal(
    buildAuthenticationReturnPath(
      "/zh/share/agent/signed-token",
      "source=invite"
    ),
    "/zh/share/agent/signed-token?source=invite"
  );
  assert.equal(
    buildAuthenticationReturnPath("/en/share/agent/signed-token", ""),
    "/en/share/agent/signed-token"
  );
});

test("separates persistent Agent targeting from one-time menu onboarding", () => {
  assert.deepEqual(
    parseAgentUsageGuideParams(
      new URLSearchParams("tab=mine&agent_id=41&onboarding=usage-menu")
    ),
    { agentId: 41 }
  );
  assert.equal(
    parseAgentUsageGuideParams(new URLSearchParams("agent_id=41")),
    null
  );
  assert.equal(
    parseAgentUsageGuideParams(
      new URLSearchParams("agent_id=nope&onboarding=usage-menu")
    ),
    null
  );
  assert.deepEqual(
    parseAgentUsageGuideTargetParams(new URLSearchParams("agent_id=41")),
    { agentId: 41 }
  );
  assert.equal(
    parseAgentUsageGuideTargetParams(new URLSearchParams("agent_id=nope")),
    null
  );
  assert.equal(
    clearAgentUsageGuidePath("zh", 41),
    "/zh/agent-space?tab=mine&agent_id=41"
  );
});

test("resolves a published Agent outside the current repository page", () => {
  const currentPageAgents = [{ agent_id: 7, name: "current" }];
  const targetedAgent = { agent_id: 41, name: "target" };

  assert.deepEqual(
    resolveAgentUsageGuideTarget({
      agentId: 41,
      agents: currentPageAgents,
      fallbackAgent: targetedAgent,
      isListLoading: false,
      isFallbackLoading: false,
      getAgentId: (agent) => agent.agent_id,
    }),
    { state: "found", agent: targetedAgent }
  );
});

test("waits for guide target queries and rejects a mismatched fallback", () => {
  assert.deepEqual(
    resolveAgentUsageGuideTarget({
      agentId: 41,
      agents: [] as Array<{ agent_id: number }>,
      fallbackAgent: null,
      isListLoading: true,
      isFallbackLoading: true,
      getAgentId: (agent) => agent.agent_id,
    }),
    { state: "loading" }
  );
  assert.deepEqual(
    resolveAgentUsageGuideTarget({
      agentId: 41,
      agents: [],
      fallbackAgent: { agent_id: 42 },
      isListLoading: false,
      isFallbackLoading: false,
      getAgentId: (agent) => agent.agent_id,
    }),
    { state: "missing" }
  );
});

test("opens a repository guide target only once", () => {
  const target = { agent_id: 41, name: "target" };
  assert.deepEqual(
    getAgentUsageGuideOpenAction({
      agentId: 41,
      consumedAgentId: null,
      target: { state: "found", agent: target },
    }),
    { action: "open", agent: target }
  );
  assert.deepEqual(
    getAgentUsageGuideOpenAction({
      agentId: 41,
      consumedAgentId: 41,
      target: { state: "found", agent: target },
    }),
    { action: "ignore" }
  );
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

test("replaces rotated share links and removes revoked links immediately", () => {
  const original = { share_token: "old-token" };
  const rotated = { share_token: "new-token" };

  assert.equal(
    reduceAgentShareGuideState(original, { type: "saved", share: rotated }),
    rotated
  );
  assert.equal(reduceAgentShareGuideState(rotated, { type: "revoked" }), null);
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
    buildNorthboundRunUrl(undefined, "https://nexent.example/"),
    "https://nexent.example/nb/v1/chat/run"
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
