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
  "idle" | "clarifying" | "draft_created" | "binding" | "resources_bound";

interface ActiveNl2AgentCard {
  key: string;
  subtype: string;
}

interface Nl2AgentFlowState {
  phase: Nl2AgentFlowPhase;
  agentId: number | null;
  activeCard: ActiveNl2AgentCard | null;
  submittedCardKeys: ReadonlySet<string>;
  isFormLocked: boolean;
  sessionGeneration: number;
}

type Nl2AgentFlowAction =
  | { type: "reset"; agentId: number | null }
  | { type: "register_card"; card: ActiveNl2AgentCard }
  | { type: "submit_card"; cardKey: string }
  | { type: "draft_created"; agentId: number }
  | { type: "resources_bound"; agentId: number };

const INITIAL_STATE: Nl2AgentFlowState = {
  phase: "idle",
  agentId: null,
  activeCard: null,
  submittedCardKeys: new Set(),
  isFormLocked: false,
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
    case "draft_created":
      return {
        ...state,
        phase: "draft_created",
        agentId: action.agentId,
        activeCard: null,
        isFormLocked: true,
      };
    case "resources_bound":
      return {
        ...state,
        phase: "resources_bound",
        agentId: action.agentId,
        isFormLocked: true,
      };
  }
}

interface Nl2AgentFlowContextValue extends Nl2AgentFlowState {
  resetFlow: (agentId?: number | null) => void;
  registerCard: (key: string, subtype: string) => void;
  submitCard: (key: string) => void;
  markDraftCreated: (agentId: number) => void;
  markResourcesBound: (agentId: number) => void;
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
  const markDraftCreated = useCallback(
    (agentId: number) => dispatch({ type: "draft_created", agentId }),
    []
  );
  const markResourcesBound = useCallback(
    (agentId: number) => dispatch({ type: "resources_bound", agentId }),
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
      markDraftCreated,
      markResourcesBound,
      isCardInteractive,
    }),
    [
      isCardInteractive,
      markDraftCreated,
      markResourcesBound,
      registerCard,
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
