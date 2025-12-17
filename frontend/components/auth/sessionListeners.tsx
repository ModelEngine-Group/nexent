"use client";

import { useEffect, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { App, Modal } from "antd";
import { AlertCircle } from "lucide-react";

import { useAuth } from "@/hooks/useAuth";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { authService } from "@/services/authService";
import { sessionService } from "@/services/sessionService";
import { getSessionFromStorage } from "@/lib/auth";
import { EVENTS } from "@/const/auth";
import {
  TOKEN_REFRESH_BEFORE_EXPIRY_MS,
  MIN_ACTIVITY_CHECK_INTERVAL_MS,
} from "@/const/constants";
import log from "@/lib/logger";
import { saveView } from "@/lib/viewPersistence";

/**
 * Session management component
 * Handles session expiration, session refresh and other functions
 */
export function SessionListeners() {
  const router = useRouter();
  const pathname = usePathname();
  const { t } = useTranslation("common");
  const { openLoginModal, setIsFromSessionExpired, clearLocalSession, isSpeedMode } =
    useAuth();
  const { modal } = App.useApp();
  const { confirm } = useConfirmModal();
  const modalShownRef = useRef<boolean>(false);

  const isLocaleHomePath = (path?: string | null) => {
    if (!path) return false;
    const segments = path.split("/").filter(Boolean);
    return segments.length <= 1;
  };

  /**
   * Show "Login Expired" confirmation modal
   * This function handles debounce logic to prevent modal from appearing repeatedly
   */
  const showSessionExpiredModal = () => {
    // If already shown, return directly
    if (modalShownRef.current) return;
    modalShownRef.current = true;

    modal.confirm({
      title: t("login.expired.title"),
      icon: <AlertCircle />,
      content: t("login.expired.content"),
      okText: t("login.expired.okText"),
      cancelText: t("login.expired.cancelText"),
      centered: true,
      closable: false,
      okButtonProps: { 
        danger: true, 
        type: "primary"
      },
      onOk() {
        // Clear local session state (session already expired on backend)
        clearLocalSession();
        // Mark the source as session expired
        setIsFromSessionExpired(true);
        Modal.destroyAll();
        openLoginModal();
        setTimeout(() => (modalShownRef.current = false), 500);
      },
      onCancel() {
        // Clear local session state (session already expired on backend)
        clearLocalSession();
        saveView("home");
        router.push("/");
        setTimeout(() => (modalShownRef.current = false), 500);
      },
    });
  };

  // Listen for events after successful login, reset modalShown state
  useEffect(() => {
    const handleModalClosed = () => {
      modalShownRef.current = false;
    };

    // Add event listener
    document.addEventListener("modalClosed", handleModalClosed);

    // Cleanup function
    return () => {
      document.removeEventListener("modalClosed", handleModalClosed);
    };
  }, []);

  // Listen for session expiration events (skip in speed mode)
  useEffect(() => {
    if (isSpeedMode) return;
    const handleSessionExpired = (event: CustomEvent) => {
      // Directly call the wrapper function
      showSessionExpiredModal();
    };

    // Add event listener
    window.addEventListener(
      EVENTS.SESSION_EXPIRED,
      handleSessionExpired as EventListener
    );

    // Cleanup function
    return () => {
      window.removeEventListener(
        EVENTS.SESSION_EXPIRED,
        handleSessionExpired as EventListener
      );
    };
    // Remove confirm from dependency array to avoid duplicate registration due to function reference changes
  }, [isSpeedMode]);

  // When component first mounts, if no local session is found, show modal immediately
  useEffect(() => {
    // Skip in speed mode
    if (isSpeedMode) return;
  }, []);

  // Session status check
  useEffect(() => {
    // Skip in speed mode
    if (isSpeedMode) return;
    // Check session status on first load
    const checkSession = async () => {
      try {
        // Capture whether there was a local session before validation
        const hadLocalSession =
          typeof window !== "undefined" && !!localStorage.getItem("session");

        // Try to get current session
        const session = await authService.getSession();

        // Only show session expired modal if a prior session existed and is now invalid
        if ((!session && hadLocalSession) || (!session && !hadLocalSession && !isLocaleHomePath(pathname))) {
          window.dispatchEvent(
            new CustomEvent(EVENTS.SESSION_EXPIRED, {
              detail: { message: "Session expired, please sign in again" },
            })
          );
        }
      } catch (error) {
        log.error("Error checking session status:", error);
      }
    };

    checkSession();
  }, [pathname, isSpeedMode]);

  // Sliding expiration: refresh token shortly before expiry on user activity (skip in speed mode)
  useEffect(() => {
    if (isSpeedMode) return;

    let lastActivityCheckAt = 0;

    const maybeRefreshOnActivity = async () => {
      try {
        // Throttle activity-driven checks
        const now = Date.now();
        if (now - lastActivityCheckAt < MIN_ACTIVITY_CHECK_INTERVAL_MS) return;
        lastActivityCheckAt = now;

        // Do not run when page is hidden
        if (typeof document !== "undefined" && document.hidden) return;

        const sessionObj = getSessionFromStorage();
        if (!sessionObj?.expires_at) return;

        const msUntilExpiry = sessionObj.expires_at * 1000 - now;
        if (msUntilExpiry <= TOKEN_REFRESH_BEFORE_EXPIRY_MS) {
          const ok = await sessionService.checkAndRefreshToken();
          if (!ok) {
            // If refresh failed and token is already expired, raise expired flow
            if (msUntilExpiry <= 0) {
              window.dispatchEvent(
                new CustomEvent(EVENTS.SESSION_EXPIRED, {
                  detail: { message: "Session expired, please sign in again" },
                })
              );
            }
          }
        }
      } catch (error) {
        log.error("Activity-based refresh check failed:", error);
      }
    };

    const events: (keyof DocumentEventMap | keyof WindowEventMap)[] = [
      "click",
      "keydown",
      "mousemove",
      "touchstart",
      "focus",
      "visibilitychange",
    ];

    const handler = () => {
      // Wrap to avoid passing the event into async function
      void maybeRefreshOnActivity();
    };

    events.forEach((evt) => {
      // Use window for focus/visibility, document for input/mouse
      if (evt === "focus" || evt === "visibilitychange") {
        window.addEventListener(evt as any, handler, { passive: true });
      } else {
        document.addEventListener(evt as any, handler, { passive: true });
      }
    });

    return () => {
      events.forEach((evt) => {
        if (evt === "focus" || evt === "visibilitychange") {
          window.removeEventListener(evt as any, handler as any);
        } else {
          document.removeEventListener(evt as any, handler as any);
        }
      });
    };
  }, [isSpeedMode]);

  // This component doesn't render UI elements
  return null;
}
