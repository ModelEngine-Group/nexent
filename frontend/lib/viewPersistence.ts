/**
 * View persistence utilities for managing current view state across page refreshes
 * Uses localStorage to persist the current view selection
 */

const VIEW_STORAGE_KEY = 'nexent_current_view';

type ViewType =
  | "home"
  | "memory"
  | "models"
  | "agents"
  | "knowledges"
  | "space"
  | "setup"
  | "chat"
  | "market"
  | "users"
  | "mcpTools"
  | "monitoring";

const VALID_VIEWS: ViewType[] = [
  "home",
  "memory",
  "models",
  "agents",
  "knowledges",
  "space",
  "setup",
  "chat",
  "market",
  "users",
  "mcpTools",
  "monitoring",
];

/**
 * Get the saved view from localStorage
 * @returns The saved view or "home" as default
 */
export function getSavedView(): ViewType {
  if (typeof window === 'undefined') {
    return "home";
  }

  try {
    const savedView = localStorage.getItem(VIEW_STORAGE_KEY);
    if (savedView && VALID_VIEWS.includes(savedView as ViewType)) {
      return savedView as ViewType;
    }
  } catch (error) {
    // localStorage might be disabled or throw errors
    console.warn('Failed to read saved view from localStorage:', error);
  }

  return "home";
}

/**
 * Save the current view to localStorage
 * @param view The view to save
 */
export function saveView(view: ViewType): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    localStorage.setItem(VIEW_STORAGE_KEY, view);
  } catch (error) {
    // localStorage might be disabled or throw errors
    console.warn('Failed to save view to localStorage:', error);
  }
}

/**
 * Clear the saved view from localStorage
 */
export function clearSavedView(): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    localStorage.removeItem(VIEW_STORAGE_KEY);
  } catch (error) {
    console.warn('Failed to clear saved view from localStorage:', error);
  }
}

