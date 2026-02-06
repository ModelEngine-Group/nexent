"use client";

import { useState, useEffect, useLayoutEffect, useCallback, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, usePathname } from "next/navigation";
import { User, AuthInfoResponse, AuthorizationContextType } from "@/types/auth";
import { getSessionFromStorage } from "@/lib/session";
import { authService } from "@/services/authService";
import { authEvents, authzEvents, authzEventUtils } from "@/lib/authEvents";
import { AUTH_EVENTS, AUTHZ_EVENTS } from "@/const/auth";
import { getEffectiveRoutePath } from "@/lib/auth";
import log from "@/lib/logger";
import { useDeployment } from "@/components/providers/deploymentProvider";

/**
 * Custom hook for authorization management
 * Handles user permissions, accessible routes, and React Query caching
 */
export function useAuthorization(): AuthorizationContextType {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  const { isSpeedMode } = useDeployment();

  const [user, setUser] = useState<User | null>(null);
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [accessibleRoutes, setAccessibleRoutes] = useState<string[]>([]);
  const [lastCheckedPath, setLastCheckedPath] = useState<string | null>(null);

  // Authz prompt modal state (permission denied)
  const [isAuthzPromptModalOpen, setIsAuthzPromptModalOpen] = useState(false);

  // True when authorization data is ready (permissions loaded)
  const [isAuthzReady, setIsAuthzReady] = useState(false);

  // Track if initialization has been attempted to prevent duplicate calls
  const initializationAttemptedRef = useRef(false);

  // Query for current user authorization info
  // enabled: false prevents automatic query execution on mount
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
    enabled: false, // Disabled by default, enabled by manual refetch() calls
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  });

  // Update state when authorization data is received
  useEffect(() => {
    if (isLoading) return;
    // Handle API error or null response (e.g., token expired)
    if (!currentUserInfo) {
      log.warn("Failed to get user info, clearing authorization state");
      setUser(null);
      setGroupIds([]);
      setPermissions([]);
      setAccessibleRoutes([]);
      return;
    }

    if (typeof currentUserInfo === "object") {
      // API returns: { user: { permissions, accessibleRoutes, ...userInfo } }
      const { user } = currentUserInfo;

      if (user) {
        const { permissions, accessibleRoutes, groupIds, ...userInfo } = user;
        // Only update if we have permissions (full user info)
        if (permissions && accessibleRoutes) {
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


        } else {
          log.warn("Missing permissions or accessibleRoutes in user info", {
            hasPermissions: !!permissions,
            hasAccessibleRoutes: !!accessibleRoutes,
          });
        }
      }
    }
  }, [currentUserInfo, isLoading, error]);

  // Listen for authentication events
  useEffect(() => {
    if (isSpeedMode) return;
    // Handle login success - set user info immediately, then fetch full permissions
    const handleLoginSuccess = () => {
      refetch().then((result) => {
        // Manually process the data if refetch succeeded
        // This is needed because with enabled: false, React Query might not update data automatically
        // Check both status string and isSuccess boolean for compatibility
        if (result.data && (result.status === 'success' || result.isSuccess)) {
          const { user } = result.data;

          if (user) {
            const { permissions, accessibleRoutes, groupIds, ...userInfo } = user;

            if (permissions && accessibleRoutes) {
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
            } else {
              log.warn("Missing permissions or accessibleRoutes in refetch result");
            }
          }
        }
      }).catch((error) => {
        log.error("Refetch failed:", error);
      });
    };

    // Handle logout - clear authorization data
    const handleLogout = () => {
      log.info("User logged out, clearing authorization data...");
      setUser(null);
      setGroupIds([]);
      setPermissions([]);
      setAccessibleRoutes([]);
      setIsAuthzReady(false);
    };

    // Handle session expired - clear authorization data
    const handleSessionExpired = () => {
      log.info("Session expired, clearing authorization data...");
      setUser(null);
      setGroupIds([]);
      setPermissions([]);
      setAccessibleRoutes([]);
      setIsAuthzReady(false);
    };

    // Register event listeners
    const cleanupLogin = authEvents.on(
      AUTH_EVENTS.LOGIN_SUCCESS,
      handleLoginSuccess
    );
    const cleanupLogout = authEvents.on(AUTH_EVENTS.LOGOUT, handleLogout);
    const cleanupSessionExpired = authEvents.on(
      AUTH_EVENTS.SESSION_EXPIRED,
      handleSessionExpired
    );

    return () => {
      cleanupLogin();
      cleanupLogout();
      cleanupSessionExpired();
    };
  }, [refetch]);

  // Initialize authorization data on mount if user is already authenticated
  useEffect(() => {
    // Prevent duplicate initialization attempts
    if (initializationAttemptedRef.current) {
      return;
    }

    const initializeAuthz = () => {
      // Check if data already exists in cache and is still fresh
      const cachedData = queryClient.getQueryData<AuthInfoResponse>(["currentUserInfo"]);
      const queryState = queryClient.getQueryState(["currentUserInfo"]);

      // If we have cached data, check if it's still fresh (within staleTime)
      if (cachedData && queryState) {
        // Check if data is fresh (updated within staleTime)
        if (queryState.dataUpdatedAt) {
          const timeSinceUpdate = Date.now() - queryState.dataUpdatedAt;
          const staleTime = 5 * 60 * 1000; // 5 minutes
          if (timeSinceUpdate < staleTime) {
            log.info("Using cached authorization data, skipping refetch", {
              timeSinceUpdate: Math.round(timeSinceUpdate / 1000) + "s",
            });
            // Data will be processed by the useEffect that watches currentUserInfo
            initializationAttemptedRef.current = true;
            return;
          }
        } else if (cachedData) {
          // If we have cached data but no timestamp, still use it to avoid unnecessary refetch
          // This can happen if data was set manually or from a previous session
          log.info("Using cached authorization data (no timestamp), skipping refetch");
          initializationAttemptedRef.current = true;
          return;
        }
      }

      // In speed mode, always fetch authorization info
      // In full mode, only fetch if session exists
      if (!isSpeedMode) {
        const session = getSessionFromStorage();
        if (!session?.access_token) {
          initializationAttemptedRef.current = true;
          return;
        }
        const now = Date.now();
        const expiresAt = session.expires_at * 1000;

        if (expiresAt <= now) {
          initializationAttemptedRef.current = true;
          return;
        }
      }

      log.info(
        isSpeedMode
          ? "Speed mode: fetching authorization info..."
          : "Valid session found on initialization, fetching authorization info..."
      );
      initializationAttemptedRef.current = true;
      refetch().catch((error) => {
        log.error("Initial refetch error:", error);
      });
    };

    // Small delay to ensure authentication state is initialized
    const timeoutId = setTimeout(initializeAuthz, 100);
    return () => clearTimeout(timeoutId);
  }, [isSpeedMode, refetch, queryClient]);

  // Authz prompt modal control functions (defined before useLayoutEffect)
  const openAuthzPromptModal = useCallback(() => setIsAuthzPromptModalOpen(true), []);
  const closeAuthzPromptModal = useCallback(() => setIsAuthzPromptModalOpen(false), []);

  // Check if current route has access (computed on each render)
  const cleanPath = getEffectiveRoutePath(pathname);
  const hasAccess = accessibleRoutes.includes(cleanPath);

  // Route guard - check authorization when pathname changes
  // Use useLayoutEffect to prevent flash of unauthorized content
  useLayoutEffect(() => {
    // Skip if still loading authorization data
    if (isLoading) return;

    // Skip if no user (not authenticated) - authentication should be handled by useAuthentication
    if (!user) return;

    // Skip if no accessible routes loaded yet
    if (accessibleRoutes.length === 0) return;

    // Skip if pathname hasn't changed
    if (pathname === lastCheckedPath) return;

    if (!hasAccess) {
      log.warn("Access denied to route:", { pathname: cleanPath, accessibleRoutes });
      // Only show authz prompt if user is fully authenticated
      if (user) {
        openAuthzPromptModal();
      }
      // Use setTimeout to ensure redirect happens after current render cycle
      setTimeout(() => {
        router.replace("/");
      }, 0);
      return;
    }

    // Update last checked path to avoid redundant checks
    setLastCheckedPath(pathname);
  }, [pathname, isLoading, user, accessibleRoutes, lastCheckedPath, hasAccess, router, openAuthzPromptModal]);

  // Permission checking utilities
  const hasPermission = (permission: string): boolean => {
    return permissions.includes(permission);
  };

  const hasAnyPermission = (requiredPermissions: string[]): boolean => {
    return requiredPermissions.some((permission) =>
      permissions.includes(permission)
    );
  };

  const canAccessRoute = (route: string): boolean => {
    return accessibleRoutes.includes(route);
  };

  return {
    // Authorization data
    user,
    groupIds,
    permissions,
    accessibleRoutes,

    // State
    isLoading,
    error: error as Error | null,

    // Authorization status
    // True when authorization is complete and user has permission to access current route
    isAuthorized: !isLoading && !!user && hasAccess,

    // True when authorization data is ready (permissions loaded)
    isAuthzReady,

    // Methods
    refetch,
    hasPermission,
    hasAnyPermission,
    canAccessRoute,

    // Authz prompt modal (permission denied)
    isAuthzPromptModalOpen,
    openAuthzPromptModal,
    closeAuthzPromptModal,
  };
}
