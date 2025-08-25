"use client"

import { createContext, useReducer, useContext, ReactNode, useCallback } from "react"

// UI state interface
export interface UIState {
  isDragging: boolean;
  isCreateModalVisible: boolean;
  isDocModalVisible: boolean;
  notifications: {
    id: string;
    message: string;
    type: 'success' | 'error' | 'info' | 'warning';
  }[];
}

// UI action type
export type UIAction = 
  | { type: 'SET_DRAGGING', payload: boolean }
  | { type: 'TOGGLE_CREATE_MODAL', payload: boolean }
  | { type: 'TOGGLE_DOC_MODAL', payload: boolean }
  | { type: 'ADD_NOTIFICATION', payload: { message: string; type: 'success' | 'error' | 'info' | 'warning' } }
  | { type: 'REMOVE_NOTIFICATION', payload: string };

// Generate unique ID for notifications
const generateId = () => {
  return Date.now().toString(36) + Math.random().toString(36).substring(2);
};

// Reducer function
const uiReducer = (state: UIState, action: UIAction): UIState => {
  switch (action.type) {
    case 'SET_DRAGGING':
      return {
        ...state,
        isDragging: action.payload
      };
    case 'TOGGLE_CREATE_MODAL':
      return {
        ...state,
        isCreateModalVisible: action.payload
      };
    case 'TOGGLE_DOC_MODAL':
      return {
        ...state,
        isDocModalVisible: action.payload
      };
    case 'ADD_NOTIFICATION':
      const newNotification = {
        id: generateId(),
        message: action.payload.message,
        type: action.payload.type
      };
      return {
        ...state,
        notifications: [...state.notifications, newNotification]
      };
    case 'REMOVE_NOTIFICATION':
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
  showNotification: (message: string, type: 'success' | 'error' | 'info' | 'warning') => void;
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
    dispatch({ type: 'SET_DRAGGING', payload: isDragging });
  }, []);

  // Modal toggling
  const toggleCreateModal = useCallback((isVisible: boolean) => {
    dispatch({ type: 'TOGGLE_CREATE_MODAL', payload: isVisible });
  }, []);

  const toggleDocModal = useCallback((isVisible: boolean) => {
    dispatch({ type: 'TOGGLE_DOC_MODAL', payload: isVisible });
  }, []);

  // Notification handling
  const showNotification = useCallback((message: string, type: 'success' | 'error' | 'info' | 'warning') => {
    dispatch({ type: 'ADD_NOTIFICATION', payload: { message, type } });
  }, []);

  const removeNotification = useCallback((id: string) => {
    dispatch({ type: 'REMOVE_NOTIFICATION', payload: id });
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