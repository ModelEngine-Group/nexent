// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useRef } from "react";
import type { AssistantRuntime } from "@assistant-ui/react";
import {
  readWorkbenchDraft,
  workbenchDraftKey,
  writeWorkbenchDraft,
} from "@/lib/workbenchDrafts";

type Mode = "planning" | "execution";

export function useWorkbenchComposerDraft({
  runtime,
  identity,
  threadId,
  conversationId,
  enabled,
  isRunning,
  mode,
  setMode,
}: {
  runtime: AssistantRuntime;
  identity?: string;
  threadId?: string;
  conversationId?: string;
  enabled: boolean;
  isRunning: boolean;
  mode: Mode;
  setMode: (mode: Mode) => void;
}) {
  const current = useRef<{ key: string; threadId: string } | undefined>(
    undefined
  );
  const previous = useRef<
    { key: string; threadId: string; identity: string } | undefined
  >(undefined);
  const modeRef = useRef(mode);
  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);
  const key = identity
    ? workbenchDraftKey(identity, conversationId)
    : undefined;

  useEffect(() => {
    if (!enabled || !identity || !key || !threadId) return;
    const last = previous.current;
    if (last && last.identity !== identity) runtime.thread.composer.setText("");
    if (
      !conversationId &&
      last?.identity === identity &&
      last.threadId !== threadId
    ) {
      writeWorkbenchDraft(key);
    }
    if (
      conversationId &&
      last?.identity === identity &&
      last.threadId === threadId &&
      last.key !== key
    ) {
      const pending = readWorkbenchDraft(last.key);
      if (pending?.owner === threadId) {
        writeWorkbenchDraft(key, pending);
        writeWorkbenchDraft(last.key);
      }
    }
    previous.current = { key, threadId, identity };
    const scope = { key, threadId };
    current.current = scope;
    const composer = runtime.thread.composer;
    const restored = readWorkbenchDraft(key);
    if (
      !runtime.thread.getState().isRunning &&
      !composer.getState().text &&
      restored?.text
    ) {
      modeRef.current = restored.mode;
      setMode(restored.mode);
      composer.setText(restored.text);
    }
    const save = () => {
      if (current.current !== scope) return;
      if (
        runtime.threads?.getState().mainThreadId !== undefined &&
        runtime.threads.getState().mainThreadId !== threadId
      )
        return;
      const text = composer.getState().text;
      if (!text && runtime.thread.getState().isRunning) return;
      writeWorkbenchDraft(key, {
        text,
        mode: modeRef.current,
        owner: threadId,
      });
    };
    save();
    const unsubscribe = composer.subscribe(() => queueMicrotask(save));
    return () => {
      save();
      unsubscribe();
      if (current.current === scope) current.current = undefined;
    };
  }, [runtime, identity, key, threadId, conversationId, enabled, setMode]);

  useEffect(() => {
    const scope = current.current;
    if (!scope) return;
    const text = runtime.thread.composer.getState().text;
    if (text)
      writeWorkbenchDraft(scope.key, { text, mode, owner: scope.threadId });
    else if (!isRunning) {
      const pending = readWorkbenchDraft(scope.key);
      if (pending?.owner === scope.threadId)
        runtime.thread.composer.setText(pending.text);
    }
  }, [runtime, mode, isRunning, enabled]);

  const acknowledge = useCallback(
    (submittedText: string) => {
      if (!key || !threadId) return;
      if (
        current.current?.threadId === threadId &&
        runtime.thread.composer.getState().text
      )
        return;
      for (const candidate of new Set([
        key,
        current.current?.threadId === threadId ? current.current.key : key,
      ])) {
        const draft = readWorkbenchDraft(candidate);
        if (draft?.owner === threadId && draft.text === submittedText)
          writeWorkbenchDraft(candidate);
      }
    },
    [key, threadId, runtime]
  );
  return { acknowledge };
}
