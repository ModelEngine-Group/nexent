import {useRouter} from "next/navigation";
import {useTranslation} from "react-i18next";
import {USER_ROLES} from "@/const/auth";
import {useAuthorization} from "@/hooks/auth/useAuthorization";
import {useDeployment} from "@/components/providers/deploymentProvider";

interface UseSetupFlowOptions {
  /** Whether admin role is required to access this page */
  requireAdmin?: boolean;
  /** Redirect path for non-admin users */
  nonAdminRedirect?: string;
}

interface UseSetupFlowReturn {
  // User and authorization
  user: ReturnType<typeof useAuthorization>["user"];
  isSpeedMode: boolean;
  canAccessProtectedData: boolean;

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
 * - Admin permission checks (if required)
 * - Page transition animations
 * - Common utilities (router, translation)
 * 
 * Note: Authentication and authorization are now handled by the global
 * useAuthentication and useAuthorization hooks via route guards.
 * 
 * @param options - Configuration options
 * @returns Setup flow utilities and state
 */
export function useSetupFlow(options: UseSetupFlowOptions = {}): UseSetupFlowReturn {

  const router = useRouter();
  const {t} = useTranslation();

  // Get user and deployment info for authorization checks
  const auth = useAuthorization();
  const { isSpeedMode } = useDeployment();

  // Determine if user can access protected data (speed mode or admin)
  const canAccessProtectedData = isSpeedMode || auth.user?.role === USER_ROLES.ADMIN;

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
    // User and authorization
    user: auth.user,
    isSpeedMode,
    canAccessProtectedData,

    // Animation
    pageVariants,
    pageTransition,

    // Utilities
    router,
    t,
  };
}

