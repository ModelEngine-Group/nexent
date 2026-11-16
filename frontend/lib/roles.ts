// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { User } from "@/types/auth";
import { USER_ROLES } from "@/const/auth";

const ROLE_LABEL_KEYS = new Map<string, string>([
  [USER_ROLES.SU, "user.role.superAdmin"],
  [USER_ROLES.ADMIN, "user.role.admin"],
  [USER_ROLES.DEV, "user.role.dev"],
  [USER_ROLES.USER, "user.role.user"],
  [USER_ROLES.OPS, "user.role.ops"],
  [USER_ROLES.ASSET_OWNER, "user.role.assetOwner"],
]);

export function roleLabelKey(role: string): string {
  return ROLE_LABEL_KEYS.get(role) ?? "common.unknown";
}

type RoleInput =
  Pick<User, "role" | "roles"> | readonly string[] | string | null | undefined;

/** Prefer the authoritative array; a present empty array never restores legacy grants. */
export function effectiveRoles(value: RoleInput): string[] {
  const raw =
    typeof value === "string"
      ? [value]
      : Array.isArray(value)
        ? value
        : value
          ? ((value as User).roles ?? [(value as User).role])
          : [];
  if (
    !raw.length ||
    raw.some(
      (role: string) => !Object.values(USER_ROLES).includes(role as USER_ROLES)
    )
  )
    return [];
  const roles = [...new Set<string>(raw)];
  if (
    roles.length > 1 &&
    roles.some((role) => role === "SU" || role === "ASSET_OWNER")
  )
    return [];
  return roles;
}

export function hasRole(
  value: RoleInput,
  ...roles: readonly string[]
): boolean {
  return effectiveRoles(value).some((role) => roles.includes(role));
}

export function isOperationsOnly(value: RoleInput): boolean {
  const roles = effectiveRoles(value);
  return roles.length === 1 && roles[0] === "OPS";
}
