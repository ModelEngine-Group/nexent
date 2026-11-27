// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";

import {
  DEFAULT_MONITORING_DASHBOARD_ALLOWED_ROLES,
  canViewMonitoringDashboard,
} from "@/lib/monitoringAccess";

it("UT-FE-036 defaults monitoring access to SU", () => {
  expect(DEFAULT_MONITORING_DASHBOARD_ALLOWED_ROLES).toEqual(["SU"]);
  expect(canViewMonitoringDashboard(" sU ", false)).toBe(true);
  expect(canViewMonitoringDashboard("tenant_admin", false)).toBe(false);
});

it("UT-FE-036 matches actual roles against the configured allowlist", () => {
  const userRoles = ["USER", "TeNaNt_AdMiN"];
  const allowedRoles = [" tenant_admin "];

  expect(canViewMonitoringDashboard(userRoles, false, allowedRoles)).toBe(true);
  expect(canViewMonitoringDashboard("SU", false, allowedRoles)).toBe(false);
});

it("UT-FE-036 denies access through retired SPEED", () => {
  expect(canViewMonitoringDashboard("SU", true)).toBe(true);
  expect(canViewMonitoringDashboard("TENANT_ADMIN", true)).toBe(false);
  expect(canViewMonitoringDashboard(undefined, true, ["SPEED"])).toBe(false);
  expect(canViewMonitoringDashboard(" speed ", false, ["SPEED"])).toBe(false);
});

it("UT-FE-036 denies unmatched roles and an empty allowlist", () => {
  expect(canViewMonitoringDashboard("UNKNOWN", false)).toBe(false);
  expect(canViewMonitoringDashboard(" ", false)).toBe(false);
  expect(canViewMonitoringDashboard(undefined, false)).toBe(false);
  expect(canViewMonitoringDashboard("SU", false, [])).toBe(false);
});
