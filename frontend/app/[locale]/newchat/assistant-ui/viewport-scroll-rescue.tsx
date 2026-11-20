// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useLayoutEffect, useRef, type FC } from "react";
import { useAuiState, useThreadViewportStore } from "@assistant-ui/react";

// Avoids the useLayoutEffect SSR warning when this tree renders on the
// server; mirrors the library's own useIsomorphicLayoutEffect pattern.
const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

/**
 * Restores chat auto-scroll for the thread viewport.
 *
 * assistant-ui 0.15.x drives viewport auto-scroll from runtime events
 * ("thread.runStart", "threads.selectionChanged") and resets its internal
 * follow flag only through those events. Under the legacy remote thread list
 * runtime the events never reach the viewport controller, so once the user
 * scrolls away (for example to reach the "branch" action on an earlier
 * message) the viewport stops following the conversation entirely: sent
 * messages and streamed replies stay below the fold.
 *
 * The triggers are rebuilt from plain state subscriptions, which work under
 * every runtime:
 * 1. A run starts -> scroll to the bottom once (mirrors
 *    scrollToBottomOnRunStart) so the new reply becomes visible.
 * 2. History finishes loading -> land at the bottom of the restored
 *    conversation (mirrors scrollToBottomOnThreadSwitch + initialize).
 * 3. While a run streams and the user is at the bottom -> keep following on
 *    every message update. The store's isAtBottom is driven by real scroll
 *    events, so scrolling away stops the follow and scrolling back resumes.
 */
export const ViewportScrollRescue: FC = () => {
  const viewport = useThreadViewportStore();
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const isLoading = useAuiState((s) => s.thread.isLoading);
  const hasMessages = useAuiState((s) => s.thread.messages.length > 0);
  // `messages` identity changes on every streamed token, which provides the
  // follow cadence while content grows.
  const messages = useAuiState((s) => s.thread.messages);

  // The bottom is "sticky" from the moment a run starts: the first streamed
  // updates can arrive before the run-start scroll event has refreshed the
  // store's isAtBottom.
  const followRef = useRef(true);

  useEffect(() => {
    // The user leaving the bottom cancels the sticky follow.
    return viewport.subscribe((state, prev) => {
      if (prev.isAtBottom && !state.isAtBottom) followRef.current = false;
    });
  }, [viewport]);

  // 1. Run start: jump to the bottom so the reply is visible.
  const prevRunningRef = useRef(false);
  useIsomorphicLayoutEffect(() => {
    const wasRunning = prevRunningRef.current;
    prevRunningRef.current = isRunning;
    if (!isRunning || wasRunning) return;
    followRef.current = true;
    viewport.getState().scrollToBottom({ behavior: "instant" });
  }, [isRunning, viewport]);

  // 2. History load: land at the bottom of the restored conversation.
  const prevLoadingRef = useRef(false);
  useIsomorphicLayoutEffect(() => {
    const wasLoading = prevLoadingRef.current;
    prevLoadingRef.current = isLoading;
    if (!wasLoading || isLoading || !hasMessages) return;
    viewport.getState().scrollToBottom({ behavior: "instant" });
  }, [isLoading, hasMessages, viewport]);

  // 3. Streaming follow: track each message update while the viewport stays
  // at the bottom. The messages-identity guard keeps this effect inert when
  // only the running flag changed (the run-start scroll already fired), so a
  // run start scrolls exactly once.
  const prevMessagesRef = useRef(messages);
  useIsomorphicLayoutEffect(() => {
    const prevMessages = prevMessagesRef.current;
    prevMessagesRef.current = messages;
    if (!isRunning) return;
    if (prevMessages === messages) return;
    if (!followRef.current && !viewport.getState().isAtBottom) return;
    viewport.getState().scrollToBottom({ behavior: "instant" });
  }, [messages, isRunning, viewport]);

  return null;
};
