"use client";

import React from "react";
import { usePermission } from "@/hooks/permission/usePermission";

interface CannotProps {
  permission: string | string[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

/**
 * Render children only when user does NOT have the permission
 * 
 * @example
 * ```tsx
 * <Cannot permission="kb:delete">
 *   <Button disabled>Delete</Button>
 * </Cannot>
 * ```
 */
export function Cannot({ permission, children, fallback = null }: CannotProps) {
  const { isReady, can, canAny } = usePermission();

  if (!isReady) return null;

  const hasPermission = Array.isArray(permission)
    ? canAny(permission)
    : can(permission);

  return !hasPermission ? <>{children}</> : <>{fallback}</>;
}
