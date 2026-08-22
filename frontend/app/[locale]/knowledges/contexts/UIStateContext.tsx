"use client"

import { createContext, useReducer, useContext, ReactNode, useCallback } from "react"
import { UIState, UIAction } from "@/types/knowledgeBase"
import { UI_ACTION_TYPES, NOTIFICATION_TYPES } from "@/const/knowledgeBase"

// Generate unique ID for notifications
const generateId = () => {
  return Date.now().toString(36) + Math.random().toString(36).substring(2);
};

// Reducer function
const uiReducer = (state: UIState, action: UIAction): UIState => {
  switch (action.type) {
    case UI_ACTION_TYPES.SET_DRAGGING:
      return {
        ...state,
        isDragging: action.payload
      };
    case UI_ACTION_TYPES.TOGGLE_CREATE_MODAL:
      return {
        ...state,
        isCreateModalVisible: action.payload
      };
    case UI_ACTION_TYPES.TOGGLE_DOC_MODAL:
      return {
        ...state,
        isDocModalVisible: action.payload
      };
    case UI_ACTION_TYPES.ADD_NOTIFICATION:
      const newNotification = {
        id: generateId(),
        message: action.payload.message,
        type: action.payload.type
      };
      return {
        ...state,
        notifications: [...state.notifications, newNotification]
      };
    case UI_ACTION_TYPES.REMOVE_NOTIFICATION:
      return {
        ...state,
        notifications: state.notifications.filter(n => n.id !== action.payload)
      };
    default:
      return state;
  }
};

// Create context with default values
export const UIContext = createContext<{
  state: UIState;
  dispatch: React.Dispatch<UIAction>;
  setDragging: (isDragging: boolean) => void;
  toggleCreateModal: (isVisible: boolean) => void;
  toggleDocModal: (isVisible: boolean) => void;
  showNotification: (message: string, type: typeof NOTIFICATION_TYPES.SUCCESS | typeof NOTIFICATION_TYPES.ERROR | typeof NOTIFICATION_TYPES.INFO | typeof NOTIFICATION_TYPES.WARNING) => void;
  removeNotification: (id: string) => void;
}>({
  state: {
    isDragging: false,
    isCreateModalVisible: false,
    isDocModalVisible: false,
    notifications: []
  },
  dispatch: () => {},
  setDragging: () => {},
  toggleCreateModal: () => {},
  toggleDocModal: () => {},
  showNotification: () => {},
  removeNotification: () => {}
});

// Custom hook for using the context
export const useUIContext = () => useContext(UIContext);

// Provider component
interface UIProviderProps {
  children: ReactNode;
}

export const UIProvider: React.FC<UIProviderProps> = ({ children }) => {
  const [state, dispatch] = useReducer(uiReducer, {
    isDragging: false,
    isCreateModalVisible: false,
    isDocModalVisible: false,
    notifications: []
  });

  // Drag state handling
  const setDragging = useCallback((isDragging: boolean) => {
    dispatch({ type: UI_ACTION_TYPES.SET_DRAGGING, payload: isDragging });
  }, []);

  // Modal toggling
  const toggleCreateModal = useCallback((isVisible: boolean) => {
    dispatch({ type: UI_ACTION_TYPES.TOGGLE_CREATE_MODAL, payload: isVisible });
  }, []);

  const toggleDocModal = useCallback((isVisible: boolean) => {
    dispatch({ type: UI_ACTION_TYPES.TOGGLE_DOC_MODAL, payload: isVisible });
  }, []);

  // Notification handling
  const showNotification = useCallback((message: string, type: typeof NOTIFICATION_TYPES.SUCCESS | typeof NOTIFICATION_TYPES.ERROR | typeof NOTIFICATION_TYPES.INFO | typeof NOTIFICATION_TYPES.WARNING) => {
    dispatch({ type: UI_ACTION_TYPES.ADD_NOTIFICATION, payload: { message, type } });
  }, []);

  const removeNotification = useCallback((id: string) => {
    dispatch({ type: UI_ACTION_TYPES.REMOVE_NOTIFICATION, payload: id });
  }, []);

  return (
    <UIContext.Provider 
      value={{ 
        state, 
        dispatch,
        setDragging,
        toggleCreateModal,
        toggleDocModal,
        showNotification,
        removeNotification
      }}
    >
      {children}
    </UIContext.Provider>
  );
}; 