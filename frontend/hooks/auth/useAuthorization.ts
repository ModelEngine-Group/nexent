"use client";

import { useState, useEffect, useLayoutEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, usePathname } from "next/navigation";
import { User, AuthInfoResponse, AuthorizationContextType } from "@/types/auth";
import { authService } from "@/services/authService";
import { authEvents, authzEventUtils } from "@/lib/authEvents";
import { AUTH_EVENTS} from "@/const/auth";
import { getEffectiveRoutePath } from "@/lib/auth";
import log from "@/lib/logger";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { checkSessionValid } from "@/lib/session";

/**
 * Custom hook for authorization management
 * Handles user permissions, accessible routes, and React Query caching
 */
export function useAuthorization(): AuthorizationContextType {
  const router = useRouter();
  const pathname = usePathname();
  const { isSpeedMode } = useDeployment();

  // Authorization state
  const [user, setUser] = useState<User | null>(null);
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [accessibleRoutes, setAccessibleRoutes] = useState<string[]>([]);
  const [lastCheckedPath, setLastCheckedPath] = useState<string | null>(null);
  const [isAuthzReady, setIsAuthzReady] = useState(false);

  // Authz prompt modal state
  const [isAuthzPromptModalOpen, setIsAuthzPromptModalOpen] = useState(false);

  // Query for current user authorization info
  const {
    data: currentUserInfo,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["currentUserInfo"],
    queryFn: async (): Promise<AuthInfoResponse> => {
      const result = await authService.getCurrentUserInfo();
      if (!result) {
        throw new Error("Failed to fetch user info");
      }
      return result;
    },
    enabled: false,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    // Prevent unnecessary refetches when disabled
    refetchInterval: false,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
  });

  // Apply authorization data to state
  const applyAuthzData = useCallback(
    (data: AuthInfoResponse) => {
      const { user: userData } = data;
      if (!userData) {
        log.warn("No user data in authorization response");
        return false;
      }

      const { permissions, accessibleRoutes, groupIds, ...userInfo } = userData;
      if (!permissions || !accessibleRoutes) {
        log.warn("Missing permissions or accessibleRoutes", {
          hasPermissions: !!permissions,
          hasAccessibleRoutes: !!accessibleRoutes,
        });
        return false;
      }

      setUser(userInfo as User);
      setGroupIds(groupIds);
      setPermissions(permissions);
      setAccessibleRoutes(accessibleRoutes);
      setIsAuthzReady(true);

      authzEventUtils.emitPermissionsReady({
        ...userInfo,
        permissions,
        accessibleRoutes,
      });

      return true;
    },
    []
  );

  // Clear authorization data from state
  const clearAuthzData = useCallback(() => {
    setUser(null);
    setGroupIds([]);
    setPermissions([]);
    setAccessibleRoutes([]);
    setIsAuthzReady(false);
  }, []);

  // Fetch authorization data
  const fetchAuthzData = useCallback(() => {
    refetch()
      .then((result) => {
        if (result.data && (result.status === 'success' || result.isSuccess)) {
          applyAuthzData(result.data);
        }
      })
      .catch((err) => {
        log.error("Failed to fetch authorization data:", err);
      });
  }, [refetch, applyAuthzData]);

  // Initialize authorization on mount
  useEffect(() => {

    // In speed mode, fetch authorization data immediately
    if (isSpeedMode) {
      log.info("Speed mode: fetching authorization info...");
      fetchAuthzData();
      return;
    }

    // On page refresh, if there is a valid session in storage,
    // proactively load authorization info so that user/permissions are ready.
    if (checkSessionValid()) {
      log.info(
        "Valid session detected on mount, fetching authorization info..."
      );
      fetchAuthzData();
    }
  }, [isSpeedMode, fetchAuthzData]);

  // Listen for authentication events
  useEffect(() => {
    if (isSpeedMode) return;

    // Handle login success - fetch authorization data
    const handleLoginSuccess = () => {
      log.info("Login success: fetching authorization info...");
      fetchAuthzData();
    };

    // Handle logout - clear authorization data
    const handleLogout = () => {
      log.info("User logged out: clearing authorization data...");
      clearAuthzData();
    };

    // Handle session expired - clear authorization data
    const handleSessionExpired = () => {
      log.info("Session expired: clearing authorization data...");
      clearAuthzData();
    };

    const cleanupLogin = authEvents.on(AUTH_EVENTS.LOGIN_SUCCESS, handleLoginSuccess);
    const cleanupLogout = authEvents.on(AUTH_EVENTS.LOGOUT, handleLogout);
    const cleanupSessionExpired = authEvents.on(AUTH_EVENTS.SESSION_EXPIRED, handleSessionExpired);

    return () => {
      cleanupLogin();
      cleanupLogout();
      cleanupSessionExpired();
    };
  }, [isSpeedMode, fetchAuthzData, clearAuthzData]);

  // Authz prompt modal control functions
  const openAuthzPromptModal = useCallback(() => setIsAuthzPromptModalOpen(true), []);
  const closeAuthzPromptModal = useCallback(() => setIsAuthzPromptModalOpen(false), []);

  // Check if current route has access
  const cleanPath = getEffectiveRoutePath(pathname);
  const hasAccess = accessibleRoutes.includes(cleanPath);

  // Route guard
  useLayoutEffect(() => {
    if (isLoading || !user || accessibleRoutes.length === 0 || pathname === lastCheckedPath) {
      return;
    }

    if (!hasAccess) {
      log.warn("Access denied to route:", { pathname: cleanPath, accessibleRoutes });
      if (user) {
        openAuthzPromptModal();
      }
      setTimeout(() => {
        router.replace("/");
      }, 0);
      return;
    }

    setLastCheckedPath(pathname);
  }, [pathname, isLoading, user, accessibleRoutes, lastCheckedPath, hasAccess, cleanPath, router, openAuthzPromptModal]);

  // Permission checking utilities
  const hasPermission = useCallback((permission: string): boolean => {
    return permissions.includes(permission);
  }, [permissions]);

  const hasAnyPermission = useCallback((requiredPermissions: string[]): boolean => {
    return requiredPermissions.some((p) => permissions.includes(p));
  }, [permissions]);

  const canAccessRoute = useCallback((route: string): boolean => {
    return accessibleRoutes.includes(route);
  }, [accessibleRoutes]);

  return {
    user,
    groupIds,
    permissions,
    accessibleRoutes,
    isLoading,
    error: error as Error | null,
    isAuthorized: !isLoading && !!user && hasAccess,
    isAuthzReady,
    refetch,
    hasPermission,
    hasAnyPermission,
    canAccessRoute,
    isAuthzPromptModalOpen,
    openAuthzPromptModal,
    closeAuthzPromptModal,
  };
}
