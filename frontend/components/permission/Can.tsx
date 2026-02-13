"use client";

import React from "react";
import { usePermission } from "@/hooks/permission/usePermission";

interface CanProps {
  permission: string | string[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

/**
 * Render children only when user HAS the permission
 * 
 * @example
 * ```tsx
 * <Can permission="kb:create">
 *   <Button>Create k</Button>
 * </Can>
 * 
 * <Can permission={["kb:delete", "kb.groups:delete"]}>
 *   <DeleteButton />
 * </Can>
 * ```
 */
export function Can({ permission, children, fallback = null }: CanProps) {
  const { isReady, can, canAny } = usePermission();

  if (!isReady) return null;

  const hasPermission = Array.isArray(permission)
    ? canAny(permission)
    : can(permission);

  return hasPermission ? <>{children}</> : <>{fallback}</>;
}
