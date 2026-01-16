"use client";

import { useEffect, useRef } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useConfig } from "@/hooks/useConfig";
import { configService } from "@/services/configService";
import { EVENTS } from "@/const/auth";
import { ChatInterface } from "./internal/chatInterface";

/**
 * ChatContent component - Main chat page content
 * Handles authentication, config loading, and session management for the chat interface
 */
export default function ChatContent() {
  const { appConfig } = useConfig();
  const { user, isLoading: userLoading, isSpeedMode } = useAuth();
  const canAccessProtectedData = isSpeedMode || (!userLoading && !!user);
  const sessionExpiredTriggeredRef = useRef(false);

  useEffect(() => {
    if (!canAccessProtectedData) {
      return;
    }
    // Load config from backend when entering chat page
    configService.loadConfigToFrontend();

    if (appConfig.appName) {
      document.title = `${appConfig.appName}`;
    }
  }, [appConfig.appName, canAccessProtectedData]);

  // Require login on chat page when unauthenticated (full mode only)
  // Trigger SESSION_EXPIRED event to show "Login Expired" modal instead of directly opening login modal
  useEffect(() => {
    if (isSpeedMode) {
      sessionExpiredTriggeredRef.current = false;
      return;
    }

    if (user) {
      sessionExpiredTriggeredRef.current = false;
      return;
    }

    if (!userLoading && !sessionExpiredTriggeredRef.current) {
      sessionExpiredTriggeredRef.current = true;
      window.dispatchEvent(
        new CustomEvent(EVENTS.SESSION_EXPIRED, {
          detail: { message: "Session expired, please sign in again" },
        })
      );
    }
  }, [isSpeedMode, user, userLoading]);

  // Avoid rendering and backend calls when unauthenticated (full mode only)
  if (!canAccessProtectedData) {
    return null;
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <ChatInterface />
    </div>
  );
}
