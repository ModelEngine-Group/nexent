import assert from "node:assert/strict";
import test from "node:test";

import {
  getAgentIcon,
  getAgentUploadedIconId,
} from "../lib/chat/agentIconUtils.ts";

test("agent list ids select stable, distinct default icons", () => {
  const firstAgent = { id: "1" };
  const secondAgent = { id: "2" };

  assert.equal(getAgentIcon(firstAgent), getAgentIcon({ id: "1" }));
  assert.notEqual(getAgentIcon(firstAgent), getAgentIcon(secondAgent));
});

test("published agent ids retain their default icon", () => {
  assert.equal(
    getAgentIcon({ agent_id: 3, id: "3" }),
    getAgentIcon({ agent_id: 3, id: "different" })
  );
});

test("a saved icon takes priority only when icon_url is present", () => {
  assert.equal(
    getAgentUploadedIconId({ agent_id: 7, icon_url: "/api/agent/7/icon" }),
    7
  );
  assert.equal(getAgentUploadedIconId({ agent_id: 7, icon_url: "  " }), null);
  assert.equal(getAgentUploadedIconId({ agent_id: 7 }), null);
  assert.equal(getAgentUploadedIconId({ agent_id: 0, icon_url: "icon" }), null);
});
