import assert from "node:assert/strict";
import test from "node:test";

import { isRuntimeApiPath } from "../proxy-routing.mjs";

test("routes login-gated Agent share APIs to Runtime", () => {
  assert.equal(isRuntimeApiPath("/api/agent-share/signed-share-token"), true);
  assert.equal(
    isRuntimeApiPath("/api/agent-share/signed-share-token/history"),
    true
  );
});
