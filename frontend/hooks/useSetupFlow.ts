// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useRouter } from "next/navigation";
import { useReducedMotion } from "framer-motion";
import { useTranslation } from "react-i18next";

type UseSetupFlowOptions = Record<string, never>;

interface UseSetupFlowReturn {

  // Animation config
  pageVariants: {
    initial: { opacity: number; x: number };
    in: { opacity: number; x: number };
    out: { opacity: number; x: number };
  };
  pageTransition: {
    type: "tween";
    ease: "easeOut";
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

  void options;
  const router = useRouter();
  const { t } = useTranslation();
  const shouldReduceMotion = useReducedMotion() === true;

  // Animation variants for smooth page transitions
  const pageVariants = {
    initial: {
      opacity: shouldReduceMotion ? 1 : 0,
      x: shouldReduceMotion ? 0 : 8,
    },
    in: {
      opacity: 1,
      x: 0,
    },
    out: {
      opacity: shouldReduceMotion ? 1 : 0,
      x: shouldReduceMotion ? 0 : -8,
    },
  };

  const pageTransition = {
    type: "tween" as const,
    ease: "easeOut" as const,
    duration: shouldReduceMotion ? 0 : 0.16,
  };

  return {
    // Animation
    pageVariants,
    pageTransition,

    // Utilities
    router,
    t,
  };
}

