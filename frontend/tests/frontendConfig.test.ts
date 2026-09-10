import assert from "node:assert/strict";
import test from "node:test";

import { buildPublicFrontendConfig } from "../lib/frontendConfig.mjs";

test("exposes only configured public frontend addresses", () => {
  assert.deepEqual(
    buildPublicFrontendConfig({
      SHARE_BASE_URL: "https://share.example.com",
      NORTHBOUND_EXTERNAL_URL: "https://api.example.com/root/",
      AGENT_SHARE_TOKEN_SECRET: "must-not-leak",
    }),
    {
      shareBaseUrl: "https://share.example.com",
      northboundBaseUrl: "https://api.example.com/root",
    }
  );
});

test("omits an absent northbound public address", () => {
  assert.deepEqual(buildPublicFrontendConfig({}), { shareBaseUrl: "" });
});
