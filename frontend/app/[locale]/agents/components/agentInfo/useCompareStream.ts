"use client";

import {
  useCallback,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import { handleStreamResponse } from "@/app/chat/streaming/chatStreamHandler";
import { MESSAGE_ROLES } from "@/const/chatConfig";
import log from "@/lib/logger";
import { conversationService } from "@/services/conversationService";
import { ChatMessageType } from "@/types/chat";

type CompareSide = "left" | "right";
type CompareHistoryItem = { role: string; content: string };
type RunAgentParams = Parameters<typeof conversationService.runAgent>[0];

interface UseCompareStreamOptions {
  t: (key: string, defaultText?: string) => string;
  buildRunParams: (args: {
    side: CompareSide;
    question: string;
    conversationId: number;
    history: CompareHistoryItem[];
  }) => RunAgentParams;
  getHistory?: () => CompareHistoryItem[];
}

export function useCompareStream({
  t,
  buildRunParams,
  getHistory,
}: UseCompareStreamOptions) {
  const [leftMessages, setLeftMessages] = useState<ChatMessageType[]>([]);
  const [rightMessages, setRightMessages] = useState<ChatMessageType[]>([]);
  const [isCompareStreaming, setIsCompareStreaming] = useState(false);
  const [compareStreamingLeft, setCompareStreamingLeft] = useState(false);
  const [compareStreamingRight, setCompareStreamingRight] = useState(false);

  const compareTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const compareAbortControllersRef = useRef<{
    left: AbortController | null;
    right: AbortController | null;
  }>({ left: null, right: null });
  const compareConversationIdsRef = useRef<{
    left: number | null;
    right: number | null;
  }>({ left: null, right: null });
  const compareStepIdCountersRef = useRef<{
    left: { current: number };
    right: { current: number };
  }>({
    left: { current: 0 },
    right: { current: 0 },
  });
  const compareInFlightRef = useRef(0);

  const resetCompareTimeout = useCallback(() => {
    if (compareTimeoutRef.current) {
      clearTimeout(compareTimeoutRef.current);
    }
    compareTimeoutRef.current = setTimeout(() => {
      setIsCompareStreaming(false);
    }, 30000);
  }, []);

  const markCompareStopped = useCallback(
    (setSideMessages: (value: (prev: ChatMessageType[]) => ChatMessageType[]) => void) => {
      setSideMessages((prev) => {
        const newMessages = [...prev];
        const lastMsg = newMessages[newMessages.length - 1];
        if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
          lastMsg.isComplete = true;
          lastMsg.thinking = undefined;
          lastMsg.content = t("agent.debug.stopped");
        }
        return newMessages;
      });
    },
    [t]
  );

  const stopCompare = useCallback(async () => {
    if (compareAbortControllersRef.current.left) {
      try {
        compareAbortControllersRef.current.left.abort(t("agent.debug.userStop"));
      } catch (error) {
        log.error(t("agent.debug.cancelError"), error);
      }
    }
    if (compareAbortControllersRef.current.right) {
      try {
        compareAbortControllersRef.current.right.abort(t("agent.debug.userStop"));
      } catch (error) {
        log.error(t("agent.debug.cancelError"), error);
      }
    }

    compareAbortControllersRef.current = { left: null, right: null };

    if (compareTimeoutRef.current) {
      clearTimeout(compareTimeoutRef.current);
      compareTimeoutRef.current = null;
    }

    setIsCompareStreaming(false);
    setCompareStreamingLeft(false);
    setCompareStreamingRight(false);
    markCompareStopped(setLeftMessages);
    markCompareStopped(setRightMessages);

    const { left, right } = compareConversationIdsRef.current;
    compareConversationIdsRef.current = { left: null, right: null };

    if (left != null) {
      try {
        await conversationService.stop(left);
      } catch (error) {
        log.error(t("agent.debug.stopError"), error);
      }
    }
    if (right != null) {
      try {
        await conversationService.stop(right);
      } catch (error) {
        log.error(t("agent.debug.stopError"), error);
      }
    }
  }, [markCompareStopped, t]);

  const resetCompareState = useCallback(() => {
    setLeftMessages([]);
    setRightMessages([]);
    compareStepIdCountersRef.current.left.current = 0;
    compareStepIdCountersRef.current.right.current = 0;
    setIsCompareStreaming(false);
    setCompareStreamingLeft(false);
    setCompareStreamingRight(false);
  }, []);

  const runCompareStream = useCallback(
    async (params: {
      side: CompareSide;
      conversationId: number;
      controller: AbortController;
      setSideMessages: Dispatch<SetStateAction<ChatMessageType[]>>;
      stepIdCounterRef: { current: number };
      history: CompareHistoryItem[];
      question: string;
      onStreamEnd: () => void;
    }) => {
      try {
        const requestParams = buildRunParams({
          side: params.side,
          question: params.question,
          conversationId: params.conversationId,
          history: params.history,
        });

        const reader = await conversationService.runAgent(
          requestParams,
          params.controller.signal
        );

        if (!reader) throw new Error(t("agent.debug.nullResponse"));

        await handleStreamResponse(
          reader,
          params.setSideMessages,
          resetCompareTimeout,
          params.stepIdCounterRef,
          () => {},
          false,
          () => {},
          async () => {},
          params.conversationId,
          conversationService,
          true,
          t
        );
      } catch (error) {
        const err = error as Error;
        const isUserStop =
          err.name === "AbortError" ||
          err.message === t("agent.debug.userStop");
        if (isUserStop) {
          markCompareStopped(params.setSideMessages);
        } else {
          log.error(t("agent.debug.streamError"), error);
          const errorMessage =
            error instanceof Error
              ? error.message
              : t("agent.debug.processError");
          params.setSideMessages((prev) => {
            const newMessages = [...prev];
            const lastMsg = newMessages[newMessages.length - 1];
            if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
              lastMsg.content = errorMessage;
              lastMsg.isComplete = true;
              lastMsg.error = errorMessage;
            }
            return newMessages;
          });
        }
      } finally {
        compareInFlightRef.current -= 1;
        if (compareInFlightRef.current <= 0) {
          setIsCompareStreaming(false);
        }
        params.onStreamEnd();
      }
    },
    [buildRunParams, markCompareStopped, resetCompareTimeout, t]
  );

  const runCompare = useCallback(
    async (question: string) => {
      setIsCompareStreaming(true);
      setCompareStreamingLeft(true);
      setCompareStreamingRight(true);
      compareInFlightRef.current = 2;
      compareStepIdCountersRef.current.left.current = 0;
      compareStepIdCountersRef.current.right.current = 0;

      const now = Date.now();
      const leftUserMessage: ChatMessageType = {
        id: `${now}-left-user`,
        role: MESSAGE_ROLES.USER,
        content: question,
        timestamp: new Date(),
      };
      const rightUserMessage: ChatMessageType = {
        id: `${now}-right-user`,
        role: MESSAGE_ROLES.USER,
        content: question,
        timestamp: new Date(),
      };

      const leftAssistantMessage: ChatMessageType = {
        id: `${now}-left-assistant`,
        role: MESSAGE_ROLES.ASSISTANT,
        content: "",
        timestamp: new Date(),
        isComplete: false,
      };
      const rightAssistantMessage: ChatMessageType = {
        id: `${now}-right-assistant`,
        role: MESSAGE_ROLES.ASSISTANT,
        content: "",
        timestamp: new Date(),
        isComplete: false,
      };

      setLeftMessages([leftUserMessage, leftAssistantMessage]);
      setRightMessages([rightUserMessage, rightAssistantMessage]);

      const baseId = -Math.abs(Date.now());
      const leftConversationId = baseId;
      const rightConversationId = baseId - 1;
      compareConversationIdsRef.current = {
        left: leftConversationId,
        right: rightConversationId,
      };

      const history = getHistory ? getHistory() : [];
      const leftController = new AbortController();
      const rightController = new AbortController();
      compareAbortControllersRef.current = {
        left: leftController,
        right: rightController,
      };

      await Promise.allSettled([
        runCompareStream({
          side: "left",
          conversationId: leftConversationId,
          controller: leftController,
          setSideMessages: setLeftMessages,
          stepIdCounterRef: compareStepIdCountersRef.current.left,
          history,
          question,
          onStreamEnd: () => setCompareStreamingLeft(false),
        }),
        runCompareStream({
          side: "right",
          conversationId: rightConversationId,
          controller: rightController,
          setSideMessages: setRightMessages,
          stepIdCounterRef: compareStepIdCountersRef.current.right,
          history,
          question,
          onStreamEnd: () => setCompareStreamingRight(false),
        }),
      ]);

      compareAbortControllersRef.current = { left: null, right: null };
      if (compareTimeoutRef.current) {
        clearTimeout(compareTimeoutRef.current);
        compareTimeoutRef.current = null;
      }
    },
    [getHistory, runCompareStream]
  );

  return {
    leftMessages,
    rightMessages,
    isCompareStreaming,
    compareStreamingLeft,
    compareStreamingRight,
    runCompare,
    stopCompare,
    resetCompareState,
  };
}
