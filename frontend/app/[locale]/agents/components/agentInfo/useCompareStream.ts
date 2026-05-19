"use client";

import {
  useCallback,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import type { TFunction } from "i18next";

import { handleStreamResponse } from "@/app/chat/streaming/chatStreamHandler";
import { MESSAGE_ROLES } from "@/const/chatConfig";
import log from "@/lib/logger";
import { conversationService } from "@/services/conversationService";
import { ChatMessageType } from "@/types/chat";

type CompareSide = "left" | "right";
type CompareHistoryItem = { role: string; content: string };
type CompareHistoryMap = { left: CompareHistoryItem[]; right: CompareHistoryItem[] };
type RunAgentParams = Parameters<typeof conversationService.runAgent>[0];

interface UseCompareStreamOptions {
  t: TFunction;
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
  const translate = useCallback(
    (key: string, defaultText?: string) =>
      defaultText !== undefined ? t(key, { defaultValue: defaultText }) : t(key),
    [t]
  );
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
  const compareHistoriesRef = useRef<CompareHistoryMap>({
    left: [],
    right: [],
  });
  const compareSessionIdRef = useRef(0);
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
          lastMsg.content = translate("agent.debug.stopped");
        }
        return newMessages;
      });
    },
    [translate]
  );

  const cloneHistory = useCallback(
    (history: CompareHistoryItem[]) => history.map((item) => ({ ...item })),
    []
  );

  const ensureCompareConversationIds = useCallback(() => {
    if (
      compareConversationIdsRef.current.left !== null &&
      compareConversationIdsRef.current.right !== null
    ) {
      return {
        left: compareConversationIdsRef.current.left,
        right: compareConversationIdsRef.current.right,
      };
    }

    const baseId = -Math.abs(Date.now() + compareSessionIdRef.current);
    const nextConversationIds = {
      left: baseId,
      right: baseId - 1,
    };
    compareConversationIdsRef.current = nextConversationIds;

    return nextConversationIds;
  }, []);

  const appendCompareHistoryTurn = useCallback(
    (side: CompareSide, question: string, answer: string) => {
      compareHistoriesRef.current[side] = [
        ...compareHistoriesRef.current[side],
        { role: MESSAGE_ROLES.USER, content: question },
        { role: MESSAGE_ROLES.ASSISTANT, content: answer },
      ];
    },
    []
  );

  const stopCompare = useCallback(async () => {
    const hadActiveController =
      compareAbortControllersRef.current.left !== null ||
      compareAbortControllersRef.current.right !== null;
    const hadInFlight = compareInFlightRef.current > 0;

    if (compareAbortControllersRef.current.left) {
      try {
        compareAbortControllersRef.current.left.abort(translate("agent.debug.userStop"));
      } catch (error) {
        log.error(translate("agent.debug.cancelError"), error);
      }
    }
    if (compareAbortControllersRef.current.right) {
      try {
        compareAbortControllersRef.current.right.abort(translate("agent.debug.userStop"));
      } catch (error) {
        log.error(translate("agent.debug.cancelError"), error);
      }
    }

    compareAbortControllersRef.current = { left: null, right: null };

    if (compareTimeoutRef.current) {
      clearTimeout(compareTimeoutRef.current);
      compareTimeoutRef.current = null;
    }

    setCompareStreamingLeft(false);
    setCompareStreamingRight(false);
    markCompareStopped(setLeftMessages);
    markCompareStopped(setRightMessages);

    const { left, right } = compareConversationIdsRef.current;

    if (left != null) {
      try {
        await conversationService.stop(left);
      } catch (error) {
        log.error(translate("agent.debug.stopError"), error);
      }
    }
    if (right != null) {
      try {
        await conversationService.stop(right);
      } catch (error) {
        log.error(translate("agent.debug.stopError"), error);
      }
    }

    if (!hadActiveController && !hadInFlight) {
      setIsCompareStreaming(false);
    }
  }, [markCompareStopped, translate]);

  const resetCompareState = useCallback(() => {
    compareSessionIdRef.current += 1;
    setLeftMessages([]);
    setRightMessages([]);
    compareHistoriesRef.current = { left: [], right: [] };
    compareConversationIdsRef.current = { left: null, right: null };
    compareStepIdCountersRef.current.left.current = 0;
    compareStepIdCountersRef.current.right.current = 0;
    compareInFlightRef.current = 0;
    compareAbortControllersRef.current = { left: null, right: null };
    if (compareTimeoutRef.current) {
      clearTimeout(compareTimeoutRef.current);
      compareTimeoutRef.current = null;
    }
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
      question: string;
      onStreamEnd: () => void;
    }) => {
      const sessionId = compareSessionIdRef.current;
      const sideHistory = cloneHistory(compareHistoriesRef.current[params.side]);

      try {
        const requestParams = buildRunParams({
          side: params.side,
          question: params.question,
          conversationId: params.conversationId,
          history: sideHistory,
        });

        const guardedSetSideMessages: Dispatch<SetStateAction<ChatMessageType[]>> = (value) => {
          if (compareSessionIdRef.current !== sessionId) return;
          params.setSideMessages(value);
        };

        const reader = await conversationService.runAgent(
          requestParams,
          params.controller.signal
        );

        if (!reader) throw new Error(translate("agent.debug.nullResponse"));

        const streamResult = await handleStreamResponse(
          reader,
          guardedSetSideMessages,
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

        if (compareSessionIdRef.current === sessionId) {
          appendCompareHistoryTurn(
            params.side,
            params.question,
            streamResult.finalAnswer?.trim() || ""
          );
        }
      } catch (error) {
        const err = error as Error;
        const isUserStop =
          err.name === "AbortError" ||
          err.message === translate("agent.debug.userStop");

        if (isUserStop) {
          if (compareSessionIdRef.current === sessionId) {
            markCompareStopped(params.setSideMessages);
          }
        } else {
          log.error(translate("agent.debug.streamError"), error);
          const errorMessage =
            error instanceof Error
              ? error.message
              : translate("agent.debug.processError");
          if (compareSessionIdRef.current === sessionId) {
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
        }
      } finally {
        if (compareSessionIdRef.current === sessionId) {
          compareAbortControllersRef.current[params.side] = null;
          compareInFlightRef.current -= 1;
          if (compareInFlightRef.current <= 0) {
            setIsCompareStreaming(false);
          }
          params.onStreamEnd();
        }
      }
    },
    [
      appendCompareHistoryTurn,
      buildRunParams,
      cloneHistory,
      markCompareStopped,
      resetCompareTimeout,
      t,
      translate,
    ]
  );

  const runCompare = useCallback(
    async (question: string) => {
      const conversationIds = ensureCompareConversationIds();
      if (
        compareHistoriesRef.current.left.length === 0 &&
        compareHistoriesRef.current.right.length === 0 &&
        getHistory
      ) {
        const baseHistory = getHistory() || [];
        const clonedBaseHistory = cloneHistory(baseHistory);
        compareHistoriesRef.current = {
          left: clonedBaseHistory,
          right: cloneHistory(baseHistory),
        };
      }

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

      setLeftMessages((prev) => [...prev, leftUserMessage, leftAssistantMessage]);
      setRightMessages((prev) => [...prev, rightUserMessage, rightAssistantMessage]);

      const leftController = new AbortController();
      const rightController = new AbortController();
      compareAbortControllersRef.current = {
        left: leftController,
        right: rightController,
      };

      await Promise.allSettled([
        runCompareStream({
          side: "left",
          conversationId: conversationIds.left,
          controller: leftController,
          setSideMessages: setLeftMessages,
          stepIdCounterRef: compareStepIdCountersRef.current.left,
          question,
          onStreamEnd: () => setCompareStreamingLeft(false),
        }),
        runCompareStream({
          side: "right",
          conversationId: conversationIds.right,
          controller: rightController,
          setSideMessages: setRightMessages,
          stepIdCounterRef: compareStepIdCountersRef.current.right,
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
    [cloneHistory, ensureCompareConversationIds, getHistory, runCompareStream]
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
