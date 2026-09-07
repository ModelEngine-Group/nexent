"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useReducer,
  type FC,
  type PropsWithChildren,
} from "react";

export type Nl2AgentFlowPhase =
  | "idle"
  | "clarifying"
  | "installing"
  | "binding"
  | "generating"
  | "generation_failed"
  | "completing"
  | "completed";

export type Nl2AgentConfigFocusTarget =
  | { section: "display_info" }
  | {
      section: "role_model";
      promptTab: "duty" | "constraint" | "few-shots";
    }
  | {
      section: "tools_skills";
      capabilityTab: "tools" | "skills";
    }
  | { section: "knowledge_base" }
  | { section: "conversation_guide" };

export interface Nl2AgentConfigFocusRequest {
  agentId: number;
  target: Nl2AgentConfigFocusTarget;
  requestId: number;
}

interface ActiveNl2AgentCard {
  key: string;
  subtype: string;
}

interface Nl2AgentFlowState {
  phase: Nl2AgentFlowPhase;
  agentId: number | null;
  activeCard: ActiveNl2AgentCard | null;
  submittedCardKeys: ReadonlySet<string>;
  failedPromptFields: readonly string[];
  configFocusRequest: Nl2AgentConfigFocusRequest | null;
  completionSyncFailed: boolean;
  isFormLocked: boolean;
  isComposerDisabled: boolean;
  sessionGeneration: number;
}

type Nl2AgentFlowAction =
  | { type: "reset"; agentId: number | null }
  | { type: "register_card"; card: ActiveNl2AgentCard }
  | { type: "submit_card"; cardKey: string }
  | { type: "resources_bound"; agentId: number }
  | { type: "prompt_generation_failed"; agentId: number; fields: string[] }
  | { type: "generation_stopped"; agentId: number }
  | {
      type: "request_config_focus";
      agentId: number;
      target: Nl2AgentConfigFocusTarget;
    }
  | { type: "generation_completed"; agentId: number }
  | { type: "completion_synced"; agentId: number }
  | { type: "completion_sync_failed"; agentId: number };

const INITIAL_STATE: Nl2AgentFlowState = {
  phase: "idle",
  agentId: null,
  activeCard: null,
  submittedCardKeys: new Set(),
  failedPromptFields: [],
  configFocusRequest: null,
  completionSyncFailed: false,
  isFormLocked: false,
  isComposerDisabled: false,
  sessionGeneration: 0,
};

function reducer(
  state: Nl2AgentFlowState,
  action: Nl2AgentFlowAction
): Nl2AgentFlowState {
  switch (action.type) {
    case "reset":
      return {
        ...INITIAL_STATE,
        agentId: action.agentId,
        sessionGeneration: state.sessionGeneration + 1,
      };
    case "register_card":
      if (state.submittedCardKeys.has(action.card.key)) return state;
      return {
        ...state,
        phase:
          action.card.subtype === "requirement_clarification"
            ? "clarifying"
            : action.card.subtype === "suggested_resource_installation"
              ? "installing"
              : action.card.subtype === "installed_resource_binding"
                ? "binding"
                : state.phase,
        activeCard: action.card,
        isFormLocked: state.agentId !== null || state.isFormLocked,
      };
    case "submit_card": {
      const submittedCardKeys = new Set(state.submittedCardKeys);
      submittedCardKeys.add(action.cardKey);
      return {
        ...state,
        activeCard:
          state.activeCard?.key === action.cardKey ? null : state.activeCard,
        submittedCardKeys,
      };
    }
    case "resources_bound":
      return {
        ...state,
        phase: "generating",
        agentId: action.agentId,
        failedPromptFields: [],
        completionSyncFailed: false,
        isFormLocked: true,
      };
    case "prompt_generation_failed":
      if (state.agentId !== null && state.agentId !== action.agentId) {
        return state;
      }
      return {
        ...state,
        phase: "generation_failed",
        agentId: action.agentId,
        failedPromptFields: action.fields,
        completionSyncFailed: false,
        isFormLocked: true,
      };
    case "generation_stopped":
      if (state.agentId !== action.agentId) return state;
      return {
        ...state,
        phase: "idle",
        activeCard: null,
        failedPromptFields: [],
        configFocusRequest: null,
        completionSyncFailed: false,
        isFormLocked: false,
        isComposerDisabled: false,
      };
    case "request_config_focus":
      if (state.agentId !== null && state.agentId !== action.agentId) {
        return state;
      }
      return {
        ...state,
        configFocusRequest: {
          agentId: action.agentId,
          target: action.target,
          requestId: (state.configFocusRequest?.requestId ?? 0) + 1,
        },
      };
    case "generation_completed":
      if (state.agentId !== action.agentId) return state;
      return {
        ...state,
        phase: "completing",
        activeCard: null,
        failedPromptFields: [],
        completionSyncFailed: false,
        isFormLocked: true,
        isComposerDisabled: true,
      };
    case "completion_synced":
      if (state.agentId !== action.agentId) return state;
      return {
        ...state,
        phase: "completed",
        completionSyncFailed: false,
        isFormLocked: false,
        isComposerDisabled: false,
      };
    case "completion_sync_failed":
      if (state.agentId !== action.agentId || state.phase !== "completing") {
        return state;
      }
      return {
        ...state,
        completionSyncFailed: true,
      };
  }
}

interface Nl2AgentFlowContextValue extends Nl2AgentFlowState {
  resetFlow: (agentId?: number | null) => void;
  registerCard: (key: string, subtype: string) => void;
  submitCard: (key: string) => void;
  markResourcesBound: (agentId: number) => void;
  markPromptGenerationFailed: (agentId: number, fields: string[]) => void;
  markGenerationStopped: (agentId: number) => void;
  requestConfigFocus: (
    agentId: number,
    target: Nl2AgentConfigFocusTarget
  ) => void;
  markGenerationCompleted: (agentId: number) => void;
  markCompletionSynced: (agentId: number) => void;
  markCompletionSyncFailed: (agentId: number) => void;
  isCardInteractive: (key: string) => boolean;
}

const Nl2AgentFlowContext = createContext<Nl2AgentFlowContextValue | null>(
  null
);

export const Nl2AgentFlowProvider: FC<PropsWithChildren> = ({ children }) => {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const resetFlow = useCallback(
    (agentId: number | null = null) => dispatch({ type: "reset", agentId }),
    []
  );
  const registerCard = useCallback(
    (key: string, subtype: string) =>
      dispatch({ type: "register_card", card: { key, subtype } }),
    []
  );
  const submitCard = useCallback(
    (cardKey: string) => dispatch({ type: "submit_card", cardKey }),
    []
  );
  const markResourcesBound = useCallback(
    (agentId: number) => dispatch({ type: "resources_bound", agentId }),
    []
  );
  const markPromptGenerationFailed = useCallback(
    (agentId: number, fields: string[]) =>
      dispatch({ type: "prompt_generation_failed", agentId, fields }),
    []
  );
  const markGenerationStopped = useCallback(
    (agentId: number) => dispatch({ type: "generation_stopped", agentId }),
    []
  );
  const requestConfigFocus = useCallback(
    (agentId: number, target: Nl2AgentConfigFocusTarget) =>
      dispatch({ type: "request_config_focus", agentId, target }),
    []
  );
  const markGenerationCompleted = useCallback(
    (agentId: number) => dispatch({ type: "generation_completed", agentId }),
    []
  );
  const markCompletionSynced = useCallback(
    (agentId: number) => dispatch({ type: "completion_synced", agentId }),
    []
  );
  const markCompletionSyncFailed = useCallback(
    (agentId: number) => dispatch({ type: "completion_sync_failed", agentId }),
    []
  );
  const isCardInteractive = useCallback(
    (key: string) =>
      state.activeCard?.key === key && !state.submittedCardKeys.has(key),
    [state.activeCard, state.submittedCardKeys]
  );
  const value = useMemo(
    () => ({
      ...state,
      resetFlow,
      registerCard,
      submitCard,
      markResourcesBound,
      markPromptGenerationFailed,
      markGenerationStopped,
      requestConfigFocus,
      markGenerationCompleted,
      markCompletionSynced,
      markCompletionSyncFailed,
      isCardInteractive,
    }),
    [
      isCardInteractive,
      markGenerationCompleted,
      markCompletionSynced,
      markCompletionSyncFailed,
      markGenerationStopped,
      markPromptGenerationFailed,
      markResourcesBound,
      registerCard,
      requestConfigFocus,
      resetFlow,
      state,
      submitCard,
    ]
  );

  return (
    <Nl2AgentFlowContext.Provider value={value}>
      {children}
    </Nl2AgentFlowContext.Provider>
  );
};

export function useNl2AgentFlow(): Nl2AgentFlowContextValue {
  const context = useContext(Nl2AgentFlowContext);
  if (!context) {
    throw new Error("useNl2AgentFlow must be used within Nl2AgentFlowProvider");
  }
  return context;
}

export function useNl2AgentFormLock(): boolean {
  return useContext(Nl2AgentFlowContext)?.isFormLocked ?? false;
}
