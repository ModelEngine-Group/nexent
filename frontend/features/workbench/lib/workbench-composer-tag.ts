import { useSyncExternalStore } from "react";

export type WorkbenchComposerTag = {
  label: string;
  kind: "agent" | "skill";
};

// Module-level store for the pill-shaped category tag shown in the workbench
// composer (e.g. "智能体创建") when a landing example is clicked. Pure UI
// state shared between the landing examples and the workbench composer.
let composerTag: WorkbenchComposerTag | null = null;
const listeners = new Set<() => void>();

const subscribe = (onChange: () => void) => {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
};

const getSnapshot = () => composerTag;

export const setWorkbenchComposerTag = (next: WorkbenchComposerTag | null) => {
  composerTag = next;
  listeners.forEach((onChange) => onChange());
};

export const useWorkbenchComposerTag = () =>
  useSyncExternalStore(subscribe, getSnapshot, () => null);
