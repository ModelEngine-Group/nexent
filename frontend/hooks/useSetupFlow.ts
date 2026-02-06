import {useRouter} from "next/navigation";
import {useTranslation} from "react-i18next";
import {useAuthorization} from "@/hooks/auth/useAuthorization";
import {useDeployment} from "@/components/providers/deploymentProvider";

interface UseSetupFlowOptions {
  // Options reserved for future use
}

interface UseSetupFlowReturn {
  // User and deployment info
  user: ReturnType<typeof useAuthorization>["user"];
  isSpeedMode: boolean;

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
 * - Page transition animations
 * - Common utilities (router, translation, user info)
 *
 * Note: Authentication and authorization are handled by the global
 * useAuthentication and useAuthorization hooks via route guards.
 *
 * @param options - Configuration options
 * @returns Setup flow utilities and state
 */
export function useSetupFlow(options: UseSetupFlowOptions = {}): UseSetupFlowReturn {

  const router = useRouter();
  const {t} = useTranslation();

  // Get user and deployment info
  const auth = useAuthorization();
  const { isSpeedMode } = useDeployment();

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
    // User and deployment info
    user: auth.user,
    isSpeedMode,

    // Animation
    pageVariants,
    pageTransition,

    // Utilities
    router,
    t,
  };
}

