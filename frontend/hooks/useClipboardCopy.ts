// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
import { useAui, useAuiState } from "@assistant-ui/react";
import { copyToClipboard } from "@/lib/clipboard";

interface ClipboardCopyOptions {
  scopeKey: string;
  copiedDuration?: number;
  onCopiedChange?: (copied: boolean) => void;
  onError?: (error: unknown) => void;
}

export function useClipboardCopy({
  scopeKey,
  copiedDuration = 3000,
  onCopiedChange,
  onError,
}: ClipboardCopyOptions) {
  const [feedback, setFeedback] = useState({
    scopeKey,
    isCopied: false,
    isCopying: false,
  });
  const generation = useRef(0);
  const pending = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const feedbackTarget = useRef<((copied: boolean) => void) | undefined>(
    undefined
  );
  if (feedback.scopeKey !== scopeKey) {
    setFeedback({ scopeKey, isCopied: false, isCopying: false });
  }

  useLayoutEffect(() => {
    generation.current += 1;
    pending.current = false;
    return () => {
      generation.current += 1;
      pending.current = false;
      clearTimeout(timer.current);
      feedbackTarget.current?.(false);
      feedbackTarget.current = undefined;
    };
  }, [scopeKey]);

  const copy = useCallback(
    async (value: string): Promise<boolean> => {
      if (!value || pending.current) return false;
      pending.current = true;
      const currentGeneration = generation.current;
      clearTimeout(timer.current);
      feedbackTarget.current?.(false);
      feedbackTarget.current = undefined;
      setFeedback({ scopeKey, isCopied: false, isCopying: true });
      try {
        await copyToClipboard(value, { preserveWhitespace: true });
        if (generation.current !== currentGeneration) return false;
        setFeedback({ scopeKey, isCopied: true, isCopying: false });
        onCopiedChange?.(true);
        feedbackTarget.current = onCopiedChange;
        timer.current = setTimeout(() => {
          if (generation.current !== currentGeneration) return;
          setFeedback({ scopeKey, isCopied: false, isCopying: false });
          onCopiedChange?.(false);
          feedbackTarget.current = undefined;
        }, copiedDuration);
        return true;
      } catch (error) {
        if (generation.current !== currentGeneration) return false;
        setFeedback({ scopeKey, isCopied: false, isCopying: false });
        onError?.(error);
        return false;
      } finally {
        if (generation.current === currentGeneration) pending.current = false;
      }
    },
    [scopeKey, copiedDuration, onCopiedChange, onError]
  );

  return {
    copy,
    isCopied: feedback.scopeKey === scopeKey && feedback.isCopied,
    isCopying: feedback.scopeKey === scopeKey && feedback.isCopying,
  };
}

export function useMessageClipboardCopy(onError: (error: unknown) => void) {
  const aui = useAui();
  const scopeKey = useAuiState((s) => s.message.id);
  const editingText = useAuiState((s) =>
    s.composer.isEditing ? s.composer.text : null
  );
  const { copy, isCopying } = useClipboardCopy({
    scopeKey,
    onCopiedChange: (copied) => aui.message.setIsCopied(copied),
    onError,
  });
  const onCopy = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void copy(editingText ?? aui.message.getCopyText());
  };
  return { onCopy, isCopying };
}
