import assert from "node:assert/strict";
import test from "node:test";

import {
  CREATION_PROMPTS,
  deriveConversationMode,
  getWorkbenchSendability,
  initialWorkbenchState,
  workbenchReducer,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../features/workbench/state.ts";

test("UT-FE-WB-005 infers ordinary modes from Agent count without mode selection", () => {
  assert.equal(initialWorkbenchState.config.mode, "generic_chat");
  assert.equal(deriveConversationMode([]), "generic_chat");
  assert.equal(deriveConversationMode([{ agent_id: 8 }]), "single_agent_chat");
  assert.equal(
    deriveConversationMode([{ agent_id: 8 }, { agent_id: 9 }]),
    "multi_agent_chat"
  );
  const cleared = workbenchReducer(initialWorkbenchState, {
    type: "replace-agents",
    mounts: [],
  });
  assert.equal(cleared.config.mode, "generic_chat");
});

test("UT-FE-WB-009 creation actions clear incompatible resources", () => {
  const selected = workbenchReducer(initialWorkbenchState, {
    type: "resolve-agent-success",
    preview: {
      agent_id: 8,
      version_no: 3,
      default_skill_mounts: [{ skill_id: 4, config_values: {} }],
      knowledge: {},
    },
  });
  const creation = workbenchReducer(selected, {
    type: "select-mode",
    mode: "agent_create",
  });
  assert.equal(creation.config.mode, "agent_create");
  assert.deepEqual(creation.config.agent_mounts, []);
  assert.deepEqual(creation.config.skill_mounts, []);
});

test("UT-FE-WB-006 locks version and initializes published Skill defaults", () => {
  const state = workbenchReducer(initialWorkbenchState, {
    type: "resolve-agent-success",
    preview: {
      agent_id: 8,
      version_no: 3,
      default_skill_mounts: [
        { skill_id: 4, config_values: { language: "zh" } },
      ],
      knowledge: {},
    },
  });
  assert.deepEqual(state.config.agent_mounts, [{ agent_id: 8, version_no: 3 }]);
  assert.deepEqual(state.config.skill_mounts, [
    { skill_id: 4, config_values: { language: "zh" } },
  ]);
});

test("UT-FE-WB-007 replaces the selected Agent when multi-Agent is disabled", () => {
  const selectedA = workbenchReducer(initialWorkbenchState, {
    type: "resolve-agent-success",
    preview: {
      agent_id: 8,
      version_no: 3,
      default_skill_mounts: [],
      knowledge: {},
    },
  });
  const selectedB = workbenchReducer(selectedA, {
    type: "resolve-agent-success",
    preview: {
      agent_id: 9,
      version_no: 4,
      default_skill_mounts: [],
      knowledge: {},
    },
  });
  assert.deepEqual(selectedB.config.agent_mounts, [
    { agent_id: 9, version_no: 4 },
  ]);
  assert.equal(selectedB.config.mode, "single_agent_chat");
});

test("UT-FE-WB-008 appends unique Agents only when multi-select is requested", () => {
  const selectedA = workbenchReducer(initialWorkbenchState, {
    type: "resolve-agent-success",
    preview: {
      agent_id: 8,
      version_no: 3,
      default_skill_mounts: [],
      knowledge: {},
    },
  });
  const selectedB = workbenchReducer(selectedA, {
    type: "resolve-agent-success",
    append: true,
    preview: {
      agent_id: 9,
      version_no: 4,
      default_skill_mounts: [],
      knowledge: {},
    },
  });
  assert.deepEqual(selectedB.config.agent_mounts, [
    { agent_id: 8, version_no: 3 },
    { agent_id: 9, version_no: 4 },
  ]);
  assert.equal(selectedB.config.mode, "multi_agent_chat");
});

test("Skill full selection can be cleared", () => {
  const selected = workbenchReducer(initialWorkbenchState, {
    type: "replace-skills",
    mounts: [{ skill_id: 9, config_values: {} }],
  });
  const cleared = workbenchReducer(selected, {
    type: "replace-skills",
    mounts: [],
  });
  assert.deepEqual(cleared.config.skill_mounts, []);
});

test("Resource resolution and unavailable execution disable send", () => {
  const resolving = workbenchReducer(initialWorkbenchState, {
    type: "resolve-agent-start",
    agentId: 8,
  });
  assert.equal(getWorkbenchSendability(resolving).canSend, false);
  const multi = workbenchReducer(initialWorkbenchState, {
    type: "replace-agents",
    mounts: [{ agent_id: 8 }, { agent_id: 9 }],
  });
  assert.equal(getWorkbenchSendability(multi).canSend, false);
});

test("UT-FE-WB-032 restores canonical config and its independent version", () => {
  const config = {
    ...initialWorkbenchState.config,
    mode: "single_agent_chat" as const,
    agent_mounts: [{ agent_id: 8, version_no: 3 }],
  };
  const state = workbenchReducer(initialWorkbenchState, {
    type: "restore",
    config,
    version: 6,
  });
  assert.equal(state.configVersion, 6);
  assert.deepEqual(state.config, config);
});

test("Creation prompt catalogs each contain three examples", () => {
  assert.equal(CREATION_PROMPTS.agent_create.length, 3);
  assert.equal(CREATION_PROMPTS.skill_create.length, 3);
  assert.ok(
    [...CREATION_PROMPTS.agent_create, ...CREATION_PROMPTS.skill_create].every(
      Boolean
    )
  );
});
