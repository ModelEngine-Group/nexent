// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

/**
 * Remembers what the user was looking at in the chat home so a browser
 * refresh can return there instead of dropping them on the agent landing
 * page. Two mutually exclusive states are kept in sessionStorage (per tab,
 * so a new tab always starts on the landing):
 *
 * - a saved server conversation the user was viewing (restored by switching
 *   the runtime to that conversation, history and agent included), or
 * - the agent of a brand-new conversation that was never sent (no server
 *   conversation exists; restored as a blank conversation of that agent).
 *
 * Deep-link URL parameters always win: when one is present the stored state
 * is ignored so the link owns the initial screen.
 */

const LAST_CONVERSATION_ID_KEY = "nexent_last_chat_conversation_id";
const LAST_AGENT_ID_KEY = "nexent_last_chat_agent_id";

export interface LastChatViewState {
  /** Server-side conversation id the user was last viewing. */
  conversationId?: string;
  /** Agent id of the unsent (blank) conversation the user was composing. */
  agentId?: string;
}

const hasDeepLinkParams = (): boolean => {
  const params = new URLSearchParams(window.location.search);
  return Boolean(
    params.get("thread_id") ||
    params.get("conversation_id") ||
    params.get("agent_id")
  );
};

const readStorage = (key: string): string | undefined => {
  try {
    return window.sessionStorage.getItem(key) ?? undefined;
  } catch {
    // Storage unavailable (e.g. privacy mode): nothing to restore.
    return undefined;
  }
};

const writeStorage = (key: string, value: string): void => {
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    // Storage unavailable: the next refresh simply lands on the default view.
  }
};

const removeStorage = (key: string): void => {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // Storage unavailable: nothing to remove.
  }
};

/**
 * Read the view to restore after a refresh. Returns null when there is
 * nothing to restore, storage is unavailable, or a deep-link parameter
 * owns the initial screen. Safe during SSR (returns null without `window`).
 */
export function readLastChatViewState(): LastChatViewState | null {
  if (typeof window === "undefined") return null;
  if (hasDeepLinkParams()) return null;

  const conversationId = readStorage(LAST_CONVERSATION_ID_KEY);
  if (conversationId && /^\d+$/.test(conversationId)) {
    return { conversationId };
  }
  const agentId = readStorage(LAST_AGENT_ID_KEY);
  if (agentId && /^\d+$/.test(agentId)) {
    return { agentId };
  }
  return null;
}

/** Remember the saved conversation the user is currently viewing. */
export function writeLastChatViewConversation(conversationId: string): void {
  if (typeof window === "undefined") return;
  writeStorage(LAST_CONVERSATION_ID_KEY, conversationId);
  removeStorage(LAST_AGENT_ID_KEY);
}

/** Remember the agent of the unsent conversation the user is composing. */
export function writeLastChatViewAgent(agentId: string): void {
  if (typeof window === "undefined") return;
  writeStorage(LAST_AGENT_ID_KEY, agentId);
  removeStorage(LAST_CONVERSATION_ID_KEY);
}

/** Forget the stored view (user returned to the agent landing page). */
export function clearLastChatView(): void {
  if (typeof window === "undefined") return;
  removeStorage(LAST_CONVERSATION_ID_KEY);
  removeStorage(LAST_AGENT_ID_KEY);
}
