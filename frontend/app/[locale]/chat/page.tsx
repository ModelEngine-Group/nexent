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

  useEffect(() => {
    // Load config from backend when entering chat page
    configService.loadConfigToFrontend();

    if (appConfig.appName) {
      document.title = `${appConfig.appName}`;
    }
  }, [appConfig.appName]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <ChatInterface />
    </div>
  );
}
