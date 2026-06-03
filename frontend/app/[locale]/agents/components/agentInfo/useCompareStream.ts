"use client";

import {
  useCallback,
  useEffect,
  useMemo,
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
  persistenceKey?: string;
  persistenceEnabled?: boolean;
  persistenceFallbackKeys?: string[];
  debugStateLabel?: string;
}

const COMPARE_STORAGE_PREFIX = "agent-compare-session";
const COMPARE_STORAGE_SCHEMA_VERSION = 1;
const COMPARE_DEBUG_FLAG = "__NEXENT_COMPARE_DEBUG__";

interface PersistedCompareSession {
  version: number;
  savedAt: number;
  leftMessages: PersistedChatMessage[];
  rightMessages: PersistedChatMessage[];
  histories: CompareHistoryMap;
  conversationIds: {
    left: number | null;
    right: number | null;
  };
}

type PersistedChatMessage = {
  id: string;
  role: ChatMessageType["role"];
  content: string;
  timestamp: string;
  isComplete?: boolean;
  finalAnswer?: string;
  error?: string;
  steps?: ChatMessageType["steps"];
  searchResults?: ChatMessageType["searchResults"];
  images?: ChatMessageType["images"];
  attachments?: ChatMessageType["attachments"];
  thinking?: ChatMessageType["thinking"];
};

export function useCompareStream({
  t,
  buildRunParams,
  getHistory,
  persistenceKey,
  persistenceEnabled = true,
  persistenceFallbackKeys = [],
  debugStateLabel,
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
  const hasHydratedRef = useRef(false);
  const pendingHydratedMessageCountsRef = useRef<{
    left: number;
    right: number;
  } | null>(null);
  const [debugPersistenceState, setDebugPersistenceState] = useState("");
  const storageKey = persistenceKey
    ? `${COMPARE_STORAGE_PREFIX}:${persistenceKey}`
    : null;
  const fallbackKeySignature = persistenceFallbackKeys.join("||");
  const fallbackStorageKeys = useMemo(
    () =>
      persistenceFallbackKeys
        .map((key) => `${COMPARE_STORAGE_PREFIX}:${key}`)
        .filter((key) => key !== storageKey),
    [fallbackKeySignature, storageKey]
  );
  const isPersistenceActive = Boolean(storageKey && persistenceEnabled);
  const debugCompareLog = useCallback(
    (event: string, payload?: Record<string, unknown>) => {
      if (typeof window === "undefined") return;
      const debugFlag = (window as unknown as { [key: string]: unknown })[
        COMPARE_DEBUG_FLAG
      ];
      if (!debugFlag) return;
      log.info(`[compare-persistence] ${event}`, {
        storageKey,
        persistenceEnabled,
        ...payload,
      });
    },
    [persistenceEnabled, storageKey]
  );

  const setDebugState = useCallback(
    (event: string, extra?: string) => {
      const label = debugStateLabel ? `[${debugStateLabel}]` : "";
      setDebugPersistenceState(
        `${label}${event}${extra ? ` ${extra}` : ""}`.trim()
      );
    },
    [debugStateLabel]
  );

  const serializeMessages = useCallback(
    (messages: ChatMessageType[]): PersistedChatMessage[] =>
      messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        timestamp: message.timestamp.toISOString(),
        isComplete: message.isComplete,
        finalAnswer: message.finalAnswer,
        error: message.error,
        steps: message.steps,
        searchResults: message.searchResults,
        images: message.images,
        attachments: message.attachments,
        thinking: message.thinking,
      })),
    []
  );

  const deserializeMessages = useCallback(
    (messages: PersistedChatMessage[]) =>
      messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        timestamp: new Date(message.timestamp),
        isComplete: message.isComplete,
        finalAnswer: message.finalAnswer,
        error: message.error,
        steps: message.steps,
        searchResults: message.searchResults,
        images: message.images,
        attachments: message.attachments,
        thinking: message.thinking,
      })),
    []
  );

  const sanitizeHistory = useCallback(
    (history: unknown): CompareHistoryItem[] => {
      if (!Array.isArray(history)) return [];
      return history
        .filter(
          (item): item is CompareHistoryItem =>
            typeof item === "object" &&
            item !== null &&
            "role" in item &&
            "content" in item &&
            typeof (item as { role: unknown }).role === "string" &&
            typeof (item as { content: unknown }).content === "string"
        )
        .map((item) => ({ role: item.role, content: item.content }));
    },
    []
  );

  const sanitizeSteps = useCallback((steps: unknown): ChatMessageType["steps"] => {
    if (!Array.isArray(steps)) return undefined;
    return steps as ChatMessageType["steps"];
  }, []);

  const sanitizeSearchResults = useCallback(
    (searchResults: unknown): ChatMessageType["searchResults"] => {
      if (!Array.isArray(searchResults)) return undefined;
      return searchResults as ChatMessageType["searchResults"];
    },
    []
  );

  const sanitizeStringArray = useCallback((items: unknown): string[] | undefined => {
    if (!Array.isArray(items)) return undefined;
    return items.filter((item): item is string => typeof item === "string");
  }, []);

  const sanitizePersistedMessages = useCallback(
    (messages: unknown): PersistedChatMessage[] => {
      if (!Array.isArray(messages)) return [];
      return messages
        .filter(
          (item): item is PersistedChatMessage =>
            typeof item === "object" &&
            item !== null &&
            typeof (item as { id?: unknown }).id === "string" &&
            ((item as { role?: unknown }).role === MESSAGE_ROLES.USER ||
              (item as { role?: unknown }).role === MESSAGE_ROLES.ASSISTANT ||
              (item as { role?: unknown }).role === MESSAGE_ROLES.SYSTEM) &&
            typeof (item as { content?: unknown }).content === "string" &&
            typeof (item as { timestamp?: unknown }).timestamp === "string"
        )
        .map((item) => ({
          id: item.id,
          role: item.role,
          content: item.content,
          timestamp: item.timestamp,
          isComplete:
            typeof item.isComplete === "boolean" ? item.isComplete : undefined,
          finalAnswer:
            typeof item.finalAnswer === "string" ? item.finalAnswer : undefined,
          error: typeof item.error === "string" ? item.error : undefined,
          steps: sanitizeSteps(item.steps),
          searchResults: sanitizeSearchResults(item.searchResults),
          images: sanitizeStringArray(item.images),
          attachments: Array.isArray(item.attachments)
            ? (item.attachments as ChatMessageType["attachments"])
            : undefined,
          thinking: Array.isArray(item.thinking) ? item.thinking : undefined,
        }));
    },
    [sanitizeSearchResults, sanitizeSteps, sanitizeStringArray]
  );

  const cloneHistory = useCallback(
    (history: CompareHistoryItem[]) => history.map((item) => ({ ...item })),
    []
  );

  const readSnapshotByKey = useCallback(
    (targetKey: string): PersistedCompareSession | null => {
      if (!targetKey || typeof window === "undefined") return null;

      try {
        const raw = window.sessionStorage.getItem(targetKey);
        if (!raw) return null;

        const parsed = JSON.parse(raw) as Partial<PersistedCompareSession>;
        if (parsed.version !== COMPARE_STORAGE_SCHEMA_VERSION) return null;
        const leftMessages = sanitizePersistedMessages(parsed.leftMessages);
        const rightMessages = sanitizePersistedMessages(parsed.rightMessages);
        if (leftMessages.length === 0 && rightMessages.length === 0) {
          return null;
        }

        return {
          version: COMPARE_STORAGE_SCHEMA_VERSION,
          savedAt: Number(parsed.savedAt) || Date.now(),
          leftMessages,
          rightMessages,
          histories: {
            left: sanitizeHistory(parsed.histories?.left),
            right: sanitizeHistory(parsed.histories?.right),
          },
          conversationIds: {
            left:
              typeof parsed.conversationIds?.left === "number"
                ? parsed.conversationIds.left
                : null,
            right:
              typeof parsed.conversationIds?.right === "number"
                ? parsed.conversationIds.right
                : null,
          },
        };
      } catch (error) {
        log.error("Failed to load compare session from storage", error);
        window.sessionStorage.removeItem(targetKey);
        return null;
      }
    },
    [sanitizeHistory, sanitizePersistedMessages]
  );

  const getPersistedSnapshot = useCallback(
    (): { snapshot: PersistedCompareSession; sourceKey: string } | null => {
      if (!isPersistenceActive || !storageKey || typeof window === "undefined") return null;

      const primarySnapshot = readSnapshotByKey(storageKey);
      if (primarySnapshot) {
        return { snapshot: primarySnapshot, sourceKey: storageKey };
      }

      for (const fallbackKey of fallbackStorageKeys) {
        const fallbackSnapshot = readSnapshotByKey(fallbackKey);
        if (fallbackSnapshot) {
          return { snapshot: fallbackSnapshot, sourceKey: fallbackKey };
        }
      }

      return null;
    },
    [fallbackStorageKeys, isPersistenceActive, readSnapshotByKey, storageKey]
  );

  useEffect(() => {
    hasHydratedRef.current = false;
    pendingHydratedMessageCountsRef.current = null;

    if (!isPersistenceActive || !storageKey || typeof window === "undefined") {
      setDebugState("persistence-inactive");
      hasHydratedRef.current = true;
      return;
    }

    const restored = getPersistedSnapshot();
    if (!restored) {
      debugCompareLog("hydrate-miss");
      setDebugState("hydrate-miss", `key=${storageKey}`);
      setLeftMessages([]);
      setRightMessages([]);
      compareHistoriesRef.current = { left: [], right: [] };
      compareConversationIdsRef.current = { left: null, right: null };
      hasHydratedRef.current = true;
      return;
    }

    const { snapshot, sourceKey } = restored;
    pendingHydratedMessageCountsRef.current = {
      left: snapshot.leftMessages.length,
      right: snapshot.rightMessages.length,
    };
    setLeftMessages(deserializeMessages(snapshot.leftMessages));
    setRightMessages(deserializeMessages(snapshot.rightMessages));
    compareHistoriesRef.current = {
      left: sanitizeHistory(snapshot.histories.left),
      right: sanitizeHistory(snapshot.histories.right),
    };
    compareConversationIdsRef.current = {
      left: snapshot.conversationIds.left,
      right: snapshot.conversationIds.right,
    };
    compareStepIdCountersRef.current.left.current = 0;
    compareStepIdCountersRef.current.right.current = 0;
    debugCompareLog("hydrate-hit", {
      leftMessages: snapshot.leftMessages.length,
      rightMessages: snapshot.rightMessages.length,
      sourceKey,
    });
    setDebugState(
      "hydrate-hit",
      `from=${sourceKey.split(":").slice(-1)[0]} left=${snapshot.leftMessages.length} right=${snapshot.rightMessages.length}`
    );

    if (sourceKey !== storageKey) {
      const migratedPayload: PersistedCompareSession = {
        ...snapshot,
        histories: {
          left: cloneHistory(snapshot.histories.left),
          right: cloneHistory(snapshot.histories.right),
        },
        conversationIds: {
          ...snapshot.conversationIds,
        },
      };
      try {
        window.sessionStorage.setItem(storageKey, JSON.stringify(migratedPayload));
        window.sessionStorage.removeItem(sourceKey);
        debugCompareLog("hydrate-migrate", { from: sourceKey, to: storageKey });
        setDebugState(
          "hydrate-migrate",
          `from=${sourceKey.split(":").slice(-1)[0]} to=${storageKey.split(":").slice(-1)[0]}`
        );
      } catch (error) {
        log.error("Failed to migrate compare session storage key", error);
      }
    }
    hasHydratedRef.current = true;
  }, [
    cloneHistory,
    debugCompareLog,
    deserializeMessages,
    fallbackStorageKeys,
    getPersistedSnapshot,
    isPersistenceActive,
    setDebugState,
    sanitizeHistory,
    storageKey,
  ]);

  useEffect(() => {
    if (!isPersistenceActive || !storageKey || typeof window === "undefined") return;
    if (!hasHydratedRef.current) return;

    const pendingHydratedMessageCounts = pendingHydratedMessageCountsRef.current;
    if (pendingHydratedMessageCounts) {
      const hasHydratedMessages =
        leftMessages.length === pendingHydratedMessageCounts.left &&
        rightMessages.length === pendingHydratedMessageCounts.right;
      if (!hasHydratedMessages) {
        debugCompareLog("persist-skip-hydration-pending", {
          expectedLeft: pendingHydratedMessageCounts.left,
          expectedRight: pendingHydratedMessageCounts.right,
          currentLeft: leftMessages.length,
          currentRight: rightMessages.length,
        });
        setDebugState(
          "persist-skip-hydration",
          `expected=${pendingHydratedMessageCounts.left}/${pendingHydratedMessageCounts.right} current=${leftMessages.length}/${rightMessages.length}`
        );
        return;
      }
      pendingHydratedMessageCountsRef.current = null;
    }

    const hasPersistData =
      leftMessages.length > 0 ||
      rightMessages.length > 0 ||
      compareHistoriesRef.current.left.length > 0 ||
      compareHistoriesRef.current.right.length > 0;

    if (!hasPersistData) {
      window.sessionStorage.removeItem(storageKey);
      debugCompareLog("persist-clear");
      setDebugState("persist-clear", `key=${storageKey}`);
      return;
    }

    const payload: PersistedCompareSession = {
      version: COMPARE_STORAGE_SCHEMA_VERSION,
      savedAt: Date.now(),
      leftMessages: serializeMessages(leftMessages),
      rightMessages: serializeMessages(rightMessages),
      histories: {
        left: cloneHistory(compareHistoriesRef.current.left),
        right: cloneHistory(compareHistoriesRef.current.right),
      },
      conversationIds: { ...compareConversationIdsRef.current },
    };

    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify(payload));
      debugCompareLog("persist-save", {
        leftMessages: leftMessages.length,
        rightMessages: rightMessages.length,
      });
      setDebugState(
        "persist-save",
        `key=${storageKey.split(":").slice(-1)[0]} left=${leftMessages.length} right=${rightMessages.length}`
      );
    } catch (error) {
      log.error("Failed to persist compare session to storage", error);
    }
  }, [
    cloneHistory,
    debugCompareLog,
    isPersistenceActive,
    leftMessages,
    rightMessages,
    serializeMessages,
    setDebugState,
    storageKey,
  ]);

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
    debugPersistenceState,
  };
}
