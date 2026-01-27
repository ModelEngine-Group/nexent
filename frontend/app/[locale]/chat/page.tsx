"use client";

import { useEffect, useRef } from "react";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useConfig } from "@/hooks/useConfig";
import { configService } from "@/services/configService";
import { ChatInterface } from "./internal/chatInterface";

/**
 * ChatContent component - Main chat page content
 * Handles authentication, config loading, and session management for the chat interface
 */
export default function ChatContent() {
  const { appConfig } = useConfig();
  const { user, isLoading: userLoading } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const sessionExpiredTriggeredRef = useRef(false);

  useEffect(() => {
    // Load config from backend when entering chat page
    configService.loadConfigToFrontend();

    if (appConfig.appName) {
      document.title = `${appConfig.appName}`;
    }
  }, [appConfig.appName]);

  // Require login on chat page when unauthenticated (skip in speed mode)
  // Note: SESSION_EXPIRED event is triggered by useSessionManager.ts on initialization
  useEffect(() => {
    if (isSpeedMode) {
      sessionExpiredTriggeredRef.current = false;
      return;
    }

    if (user) {
      sessionExpiredTriggeredRef.current = false;
      return;
    }

    // Session expiration is handled by useSessionManager.ts
    // Don't trigger SESSION_EXPIRED here to avoid duplicate handling
  }, [isSpeedMode, user, userLoading]);


  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <ChatInterface />
    </div>
  );
}
