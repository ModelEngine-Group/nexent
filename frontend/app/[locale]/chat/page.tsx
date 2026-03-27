"use client";

import { useEffect } from "react";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useConfig } from "@/hooks/useConfig";
import { ChatInterface } from "./internal/chatInterface";
import "@/styles/chat.css";

/**
 * ChatContent component - Main chat page content
 * Handles authentication, config loading, and session management for the chat interface
 */
export default function ChatContent() {
  const { appConfig } = useConfig();

  useEffect(() => {
    if (appConfig?.appName) {
      document.title = `${appConfig.appName}`;
    }
  }, [appConfig?.appName]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <ChatInterface />
    </div>
  );
}
