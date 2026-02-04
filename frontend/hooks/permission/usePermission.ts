"use client";

import { useAuthorization } from "@/hooks/auth/useAuthorization";
import { useAuthentication } from "@/hooks/auth/useAuthentication";

export function usePermission() {
  const { hasPermission, hasAnyPermission, isAuthzReady, isLoading } = useAuthorization();
  const { isAuthenticated } = useAuthentication();

  return {
    isReady: isAuthzReady,
    isAuthenticated,
    isLoading,

    can: (permission: string): boolean => {
      if (!isAuthenticated || !isAuthzReady) return false;
      return hasPermission(permission);
    },

    cannot: (permission: string): boolean => {
      if (!isAuthenticated || !isAuthzReady) return true;
      return !hasPermission(permission);
    },

    canAny: (perms: string[]): boolean => {
      if (!isAuthenticated || !isAuthzReady) return false;
      return hasAnyPermission(perms);
    },

    canAll: (perms: string[]): boolean => {
      if (!isAuthenticated || !isAuthzReady) return false;
      return perms.every(p => hasPermission(p));
    },
  };
}
