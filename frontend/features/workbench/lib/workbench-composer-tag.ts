import { useSyncExternalStore } from "react";

// Module-level store for the blue category tag shown as a composer text
// prefix (e.g. "智能体创建") when a landing example is clicked. Pure UI
// state shared between the landing examples and the workbench composer.
let composerTag: string | null = null;
const listeners = new Set<() => void>();

const subscribe = (onChange: () => void) => {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
};

const getSnapshot = () => composerTag;

export const setWorkbenchComposerTag = (next: string | null) => {
  composerTag = next;
  listeners.forEach((onChange) => onChange());
};

export const useWorkbenchComposerTag = () =>
  useSyncExternalStore(subscribe, getSnapshot, () => null);
