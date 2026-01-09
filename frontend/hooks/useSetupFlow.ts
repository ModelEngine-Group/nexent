import {useState, useEffect, useRef} from "react";
import {useRouter} from "next/navigation";
import {useTranslation} from "react-i18next";

import {useAuth} from "@/hooks/useAuth";
import {
  USER_ROLES,
  CONNECTION_STATUS,
  ConnectionStatus,
} from "@/const/modelConfig";
import {EVENTS} from "@/const/auth";

interface UseSetupFlowOptions {
  /** Whether admin role is required to access this page */
  requireAdmin?: boolean;
  /** External connection status (if managed by parent) */
  externalConnectionStatus?: ConnectionStatus;
  /** External checking connection state (if managed by parent) */
  externalIsCheckingConnection?: boolean;
  /** External check connection handler (if managed by parent) */
  onCheckConnection?: () => void;
  /** Callback to expose connection status changes */
  onConnectionStatusChange?: (status: ConnectionStatus) => void;
  /** Redirect path for non-admin users */
  nonAdminRedirect?: string;
}

interface UseSetupFlowReturn {
  // Auth related
  user: any;
  isLoading: boolean;
  isSpeedMode: boolean;
  canAccessProtectedData: boolean;
  
  // Connection status
  connectionStatus: ConnectionStatus;
  isCheckingConnection: boolean;
  
  // Animation config
  pageVariants: {
    initial: { opacity: number; x: number };
    in: { opacity: number; x: number };
    out: { opacity: number; x: number };
  };
  pageTransition: {
    type: "tween";
    ease: "anticipate";
    duration: number;
  };
  
  // Utilities
  router: ReturnType<typeof useRouter>;
  t: ReturnType<typeof useTranslation>["t"];
}

/**
 * useSetupFlow - Custom hook for setup flow pages
 * 
 * Provides common functionality for setup pages including:
 * - Authentication and permission checks
 * - Connection status management
 * - Session expiration handling
 * - Page transition animations
 * 
 * @param options - Configuration options
 * @returns Setup flow utilities and state
 */
export function useSetupFlow(options: UseSetupFlowOptions = {}): UseSetupFlowReturn {
  const {
    requireAdmin = false,
    externalConnectionStatus,
    externalIsCheckingConnection,
    onCheckConnection: externalOnCheckConnection,
    onConnectionStatusChange,
    nonAdminRedirect = "/setup/knowledges",
  } = options;

  const router = useRouter();
  const {t} = useTranslation();
  const {user, isLoading: userLoading, isSpeedMode} = useAuth();
  const sessionExpiredTriggeredRef = useRef(false);

  // Calculate if user can access protected data
  const canAccessProtectedData = isSpeedMode || (!userLoading && !!user);

  // Internal connection status management (if not provided externally)
  const [internalConnectionStatus, setInternalConnectionStatus] = useState<ConnectionStatus>(
    CONNECTION_STATUS.PROCESSING
  );
  const [internalIsCheckingConnection, setInternalIsCheckingConnection] = useState(false);

  // Use external status if provided, otherwise use internal
  const connectionStatus = externalConnectionStatus ?? internalConnectionStatus;
  const isCheckingConnection = externalIsCheckingConnection ?? internalIsCheckingConnection;

  // Check login status and handle session expiration
  useEffect(() => {
    if (isSpeedMode) {
      sessionExpiredTriggeredRef.current = false;
      return;
    }

    if (user) {
      sessionExpiredTriggeredRef.current = false;
      return;
    }

    // Trigger session expired event if user is not logged in
    if (!userLoading && !sessionExpiredTriggeredRef.current) {
      sessionExpiredTriggeredRef.current = true;
      window.dispatchEvent(
        new CustomEvent(EVENTS.SESSION_EXPIRED, {
          detail: {message: "Session expired, please sign in again"},
        })
      );
    }
  }, [isSpeedMode, user, userLoading]);

  // Check admin permission if required
  useEffect(() => {
    if (!requireAdmin) return;
    
    // Only check after user is loaded
    if (userLoading) return;

    // Speed mode always has access
    if (isSpeedMode) return;

    // Check if user has admin role
    if (user && user.role !== USER_ROLES.ADMIN) {
      router.push(nonAdminRedirect);
    }
  }, [requireAdmin, isSpeedMode, user, userLoading, router, nonAdminRedirect]);


  // Animation variants for smooth page transitions
  const pageVariants = {
    initial: {
      opacity: 0,
      x: 20,
    },
    in: {
      opacity: 1,
      x: 0,
    },
    out: {
      opacity: 0,
      x: -20,
    },
  };

  const pageTransition = {
    type: "tween" as const,
    ease: "anticipate" as const,
    duration: 0.4,
  };

  return {
    // Auth
    user,
    isLoading: userLoading,
    isSpeedMode,
    canAccessProtectedData,
    
    // Connection
    connectionStatus,
    isCheckingConnection,
    
    // Animation
    pageVariants,
    pageTransition,
    
    // Utilities
    router,
    t,
  };
}

