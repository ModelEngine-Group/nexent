"use client";

import { useEffect } from "react";
import { APP_DISPLAY_NAME } from "@/const/modelConfig";
import { ChatInterface } from "./internal/chatInterface";
import "@/styles/chat.css";

/**
 * ChatContent component - Main chat page content
 * Handles authentication, config loading, and session management for the chat interface
 */
export default function ChatContent() {
  useEffect(() => {
    document.title = APP_DISPLAY_NAME;
  }, []);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <ChatInterface />
    </div>
  );
}
