import { useCallback, useEffect, useRef, useState } from "react";

import {
  resolveNl2AgentSessionByConversation,
  type Nl2AgentSessionSummary,
} from "@/services/nl2agentService";

interface UseNl2AgentSessionRecoveryOptions {
  conversationId: number | null;
  onActivate: (session: Nl2AgentSessionSummary) => void;
  onDeactivate: (conversationId: number) => void;
  onError: (error: unknown) => void;
}

export const useNl2AgentSessionRecovery = ({
  conversationId,
  onActivate,
  onDeactivate,
  onError,
}: UseNl2AgentSessionRecoveryOptions) => {
  const [sessions, setSessions] = useState<
    Record<string, Nl2AgentSessionSummary>
  >({});
  const sessionsRef = useRef(sessions);
  const nonNl2AgentConversationsRef = useRef<Set<number>>(new Set());
  const activeConversationIdRef = useRef(conversationId);
  activeConversationIdRef.current = conversationId;

  const storeSession = useCallback((session: Nl2AgentSessionSummary) => {
    const key = String(session.conversation_id);
    const next = { ...sessionsRef.current, [key]: session };
    sessionsRef.current = next;
    setSessions(next);
    nonNl2AgentConversationsRef.current.delete(session.conversation_id);
  }, []);

  const removeSession = useCallback((targetConversationId: number) => {
    const key = String(targetConversationId);
    if (!(key in sessionsRef.current)) return;
    const next = { ...sessionsRef.current };
    delete next[key];
    sessionsRef.current = next;
    setSessions(next);
  }, []);

  const resolveSession = useCallback(
    async (targetConversationId: number) => {
      const cached = sessionsRef.current[String(targetConversationId)];
      if (cached) {
        if (activeConversationIdRef.current === targetConversationId) {
          onActivate(cached);
        }
        return cached;
      }
      if (nonNl2AgentConversationsRef.current.has(targetConversationId)) {
        return null;
      }

      const session =
        await resolveNl2AgentSessionByConversation(targetConversationId);
      if (session === null) {
        nonNl2AgentConversationsRef.current.add(targetConversationId);
        removeSession(targetConversationId);
        if (activeConversationIdRef.current === targetConversationId) {
          onDeactivate(targetConversationId);
        }
        return null;
      }

      storeSession(session);
      if (activeConversationIdRef.current === targetConversationId) {
        onActivate(session);
      }
      return session;
    },
    [onActivate, onDeactivate, removeSession, storeSession]
  );

  useEffect(() => {
    if (conversationId === null) return;
    void resolveSession(conversationId).catch(onError);
  }, [conversationId, onError, resolveSession]);

  return {
    activeSession:
      conversationId === null ? undefined : sessions[String(conversationId)],
    primeSession: storeSession,
    resolveSession,
  };
};
