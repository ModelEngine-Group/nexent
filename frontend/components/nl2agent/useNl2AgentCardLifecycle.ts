"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

interface LifecycleOptions<T> {
  onSuccess?: (result: T) => void | Promise<void>;
  continuationText?: (result: T) => string | undefined;
  notifyStateChanged?: boolean;
  blockInput?: boolean;
  retainInputBlockOnError?: boolean | ((error: unknown) => boolean);
}

type LifecycleAction<T> = () => Promise<T>;

export const useNl2AgentCardLifecycle = (scopeKey: string) => {
  const workflow = useNl2AgentWorkflow();
  const {
    active,
    beginAction,
    endAction,
    setInputBlocked,
    notifyStateChanged,
    continueWithText,
    claimCardDelivery,
    completeCardDelivery,
    failCardDelivery,
  } = workflow;
  const mountedRef = useRef(true);
  const pendingRef = useRef(false);
  const retryRef = useRef<(() => Promise<unknown>) | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    mountedRef.current = true;
    pendingRef.current = false;
    retryRef.current = null;
    setPending(false);
    setError(undefined);
    return () => {
      mountedRef.current = false;
      setInputBlocked(scopeKey, false);
    };
  }, [scopeKey, setInputBlocked]);

  const execute = useCallback(
    async <T>(
      action: LifecycleAction<T>,
      options: LifecycleOptions<T> = {}
    ): Promise<T | undefined> => {
      if (!active || pendingRef.current) return undefined;
      pendingRef.current = true;
      retryRef.current = () => execute(action, options);
      setPending(true);
      setError(undefined);
      beginAction();
      if (options.blockInput) setInputBlocked(scopeKey, true);
      let succeeded = false;
      let failure: unknown;
      try {
        const result = await action();
        if (!mountedRef.current) return result;
        await options.onSuccess?.(result);
        if (options.notifyStateChanged) notifyStateChanged();
        const continuationText = options.continuationText?.(result);
        if (continuationText) {
          await continueWithText(continuationText);
        }
        succeeded = true;
        return result;
      } catch (caught) {
        failure = caught;
        if (mountedRef.current) {
          setError(
            caught instanceof Error
              ? caught.message
              : "NL2AGENT card action failed."
          );
        }
        throw caught;
      } finally {
        pendingRef.current = false;
        if (mountedRef.current) setPending(false);
        const retainInputBlock =
          typeof options.retainInputBlockOnError === "function"
            ? options.retainInputBlockOnError(failure)
            : options.retainInputBlockOnError;
        if (options.blockInput && (succeeded || !retainInputBlock)) {
          setInputBlocked(scopeKey, false);
        }
        endAction();
      }
    },
    [
      active,
      beginAction,
      continueWithText,
      endAction,
      notifyStateChanged,
      scopeKey,
      setInputBlocked,
    ]
  );

  const retry = useCallback(async () => {
    if (retryRef.current) await retryRef.current();
  }, []);

  const deliveryKey = useCallback(
    (messageId: number, cardType: string) =>
      `${scopeKey}:${messageId}:${cardType}`,
    [scopeKey]
  );

  return {
    pending,
    error,
    execute,
    retry,
    claimDelivery: (messageId: number, cardType: string) =>
      claimCardDelivery(deliveryKey(messageId, cardType)),
    completeDelivery: (messageId: number, cardType: string) =>
      completeCardDelivery(deliveryKey(messageId, cardType)),
    failDelivery: (messageId: number, cardType: string) =>
      failCardDelivery(deliveryKey(messageId, cardType)),
  };
};
