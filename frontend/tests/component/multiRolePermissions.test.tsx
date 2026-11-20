// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { describe, expect, test } from "vitest";
import { USER_ROLES } from "@/const/auth";
import { effectiveRoles, hasRole, isOperationsOnly } from "@/lib/roles";
import { canManageModels } from "@/lib/auth";

describe("authoritative role arrays", () => {
  test("preserves legacy single roles and deduplicates the complete union", () => {
    expect(effectiveRoles("ADMIN")).toEqual(["ADMIN"]);
    expect(effectiveRoles(["DEV", "OPS", "DEV"])).toEqual(["DEV", "OPS"]);
    expect(hasRole(["USER", "DEV", "OPS"], "DEV")).toBe(true);
    expect(canManageModels(["USER", "DEV", "OPS"])).toBe(true);
  });

  test("never restores a removed grant from the compatibility scalar", () => {
    expect(effectiveRoles({ role: USER_ROLES.ADMIN, roles: [] })).toEqual([]);
    expect(
      hasRole({ role: USER_ROLES.ADMIN, roles: [USER_ROLES.OPS] }, "ADMIN")
    ).toBe(false);
    expect(
      isOperationsOnly({ role: USER_ROLES.ADMIN, roles: [USER_ROLES.OPS] })
    ).toBe(true);
  });

  test.each([["SPEED"], ["UNKNOWN"], ["SU", "OPS"], ["ASSET_OWNER", "DEV"]])(
    "fails closed for invalid or mixed special identities: %j",
    (...roles) => {
      expect(effectiveRoles(roles)).toEqual([]);
      expect(canManageModels(roles)).toBe(false);
    }
  );

  test("keeps ordinary combinations distinct from an operations-only identity", () => {
    expect(isOperationsOnly(["OPS"])).toBe(true);
    expect(isOperationsOnly(["OPS", "DEV"])).toBe(false);
    expect(isOperationsOnly(["SU"])).toBe(false);
    expect(hasRole(["SU"], "SU")).toBe(true);
  });
});
