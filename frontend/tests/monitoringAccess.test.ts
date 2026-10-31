import assert from "node:assert/strict";
import test from "node:test";

import {
  canViewMonitoringDashboard,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../lib/monitoringAccess.ts";

test("preserves the default SU and speed-mode access", () => {
  assert.equal(canViewMonitoringDashboard("SU", false), true);
  assert.equal(canViewMonitoringDashboard("ADMIN", false), false);
  assert.equal(canViewMonitoringDashboard(undefined, true), true);
});

test("allows roles supplied by monitoring configuration", () => {
  const allowedRoles = ["SU", " admin ", "speed"];

  assert.equal(canViewMonitoringDashboard("ADMIN", false, allowedRoles), true);
  assert.equal(canViewMonitoringDashboard("USER", false, allowedRoles), false);
  assert.equal(canViewMonitoringDashboard(undefined, true, allowedRoles), true);
});

test("an explicitly empty allowlist hides the dashboard for every role", () => {
  assert.equal(canViewMonitoringDashboard("SU", false, []), false);
  assert.equal(canViewMonitoringDashboard(undefined, true, []), false);
});
