"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { createNl2AgentActionContext } from "@/lib/chat/nl2agentContinuation";
import {
  dispatchNl2AgentAction,
  type Nl2AgentActionDraft,
  type Nl2AgentActionRequest,
  type Nl2AgentActionResponse,
} from "@/services/nl2agentService";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

interface LifecycleOptions {
  onSuccess?: (result: Nl2AgentActionResponse) => void | Promise<void>;
  notifyStateChanged?: boolean;
  continueAfterSuccess?: boolean;
  blockInput?: boolean;
  retainInputBlockOnError?: boolean | ((error: unknown) => boolean);
}

interface PendingActionIdentity {
  fingerprint: string;
  actionId: string;
}

export const useNl2AgentCardLifecycle = (scopeKey: string) => {
  const workflow = useNl2AgentWorkflow();
  const {
    active,
    agentId,
    sessionState,
    beginAction,
    endAction,
    setInputBlocked,
    notifyStateChanged,
    continueWithAction,
  } = workflow;
  const mountedRef = useRef(true);
  const pendingRef = useRef(false);
  const actionIdentityRef = useRef<PendingActionIdentity>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    mountedRef.current = true;
    pendingRef.current = false;
    actionIdentityRef.current = undefined;
    setPending(false);
    setError(undefined);
    return () => {
      mountedRef.current = false;
      setInputBlocked(scopeKey, false);
    };
  }, [scopeKey, setInputBlocked]);

  const execute = useCallback(
    async (
      action: Nl2AgentActionDraft,
      options: LifecycleOptions = {}
    ): Promise<Nl2AgentActionResponse | undefined> => {
      if (!active || pendingRef.current) return undefined;
      if (!agentId || !sessionState) {
        throw new Error("NL2AGENT session state is not ready.");
      }

      const fingerprint = JSON.stringify(action);
      const actionIdentity =
        actionIdentityRef.current?.fingerprint === fingerprint
          ? actionIdentityRef.current
          : { fingerprint, actionId: crypto.randomUUID() };
      actionIdentityRef.current = actionIdentity;
      const request = {
        ...action,
        action_id: actionIdentity.actionId,
        expected_revision: sessionState.revision,
      } as Nl2AgentActionRequest;

      pendingRef.current = true;
      setPending(true);
      setError(undefined);
      beginAction();
      if (options.blockInput) setInputBlocked(scopeKey, true);
      let succeeded = false;
      let failure: unknown;
      try {
        const result = await dispatchNl2AgentAction(agentId, request);
        if (result.status === "pending") {
          throw new Error("The NL2AGENT action is still being applied.");
        }
        actionIdentityRef.current = undefined;
        if (!mountedRef.current) return result;
        await options.onSuccess?.(result);
        if (options.notifyStateChanged !== false) notifyStateChanged();
        if (options.continueAfterSuccess !== false) {
          await continueWithAction(
            createNl2AgentActionContext(result, action.display_text)
          );
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
      agentId,
      beginAction,
      continueWithAction,
      endAction,
      notifyStateChanged,
      scopeKey,
      sessionState,
      setInputBlocked,
    ]
  );

  return { pending, error, execute };
};
