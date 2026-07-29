import { useSyncExternalStore } from "react";

export type A2UIFormValue = string | number | boolean | null;
export type A2UIFormValues = Record<string, A2UIFormValue>;

export interface A2UIFormSubmissionState {
  submissionId: string;
  surfaceId: string;
  sourceComponentId: string;
  status: "accepted";
}

export const A2UI_FORM_VALUES_LIMIT = 64 * 1024;

interface StagedFormSubmission {
  token: symbol;
  values: A2UIFormValues;
}

const stagedSubmissions = new Map<string, StagedFormSubmission>();
const surfaceSessions = new Map<string, string>();
const acceptedSubmissions = new Map<string, A2UIFormSubmissionState>();
const submissionListeners = new Set<() => void>();

const submissionKey = (surfaceId: string, componentId: string): string =>
  `${surfaceId}\u0000${componentId}`;

const acceptedKey = (
  sessionKey: string,
  surfaceId: string,
  componentId: string
): string => `${sessionKey}\u0000${surfaceId}\u0000${componentId}`;

const notifySubmissionListeners = (): void => {
  submissionListeners.forEach((listener) => listener());
};

const encodedSize = (value: unknown): number =>
  new TextEncoder().encode(JSON.stringify(value)).length;

export function stageA2UIFormSubmission(
  surfaceId: string,
  componentId: string,
  values: A2UIFormValues
): () => void {
  if (encodedSize(values) > A2UI_FORM_VALUES_LIMIT) {
    throw new Error("A2UI form values exceed 64 KiB");
  }
  const key = submissionKey(surfaceId, componentId);
  const token = Symbol(key);
  stagedSubmissions.set(key, { token, values: { ...values } });
  return () => {
    if (stagedSubmissions.get(key)?.token === token) {
      stagedSubmissions.delete(key);
    }
  };
}

export function consumeA2UIFormSubmission(
  surfaceId: string,
  componentId: string
): A2UIFormValues | undefined {
  const key = submissionKey(surfaceId, componentId);
  const staged = stagedSubmissions.get(key);
  if (!staged) return undefined;
  stagedSubmissions.delete(key);
  return staged.values;
}

export function clearA2UIFormSubmissions(surfaceId: string): void {
  const prefix = `${surfaceId}\u0000`;
  for (const key of stagedSubmissions.keys()) {
    if (key.startsWith(prefix)) stagedSubmissions.delete(key);
  }
}

export function parseA2UIFormSubmissionState(
  value: unknown
): A2UIFormSubmissionState | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const state = value as Record<string, unknown>;
  if (
    typeof state.submissionId !== "string" ||
    !state.submissionId ||
    typeof state.surfaceId !== "string" ||
    !state.surfaceId ||
    typeof state.sourceComponentId !== "string" ||
    !state.sourceComponentId ||
    state.status !== "accepted"
  ) {
    return null;
  }
  return {
    submissionId: state.submissionId,
    surfaceId: state.surfaceId,
    sourceComponentId: state.sourceComponentId,
    status: "accepted",
  };
}

export function registerA2UISurfaceSession(
  sessionKey: string,
  surfaceId: string
): void {
  if (surfaceSessions.get(surfaceId) === sessionKey) return;
  surfaceSessions.set(surfaceId, sessionKey);
  notifySubmissionListeners();
}

export function markA2UIFormSubmissionAccepted(
  sessionKey: string,
  state: A2UIFormSubmissionState
): void {
  registerA2UISurfaceSession(sessionKey, state.surfaceId);
  const key = acceptedKey(sessionKey, state.surfaceId, state.sourceComponentId);
  if (acceptedSubmissions.has(key)) return;
  acceptedSubmissions.set(key, state);
  notifySubmissionListeners();
}

export function isA2UIFormSubmitted(
  surfaceId: string,
  componentId: string
): boolean {
  const sessionKey = surfaceSessions.get(surfaceId);
  return Boolean(
    sessionKey &&
    acceptedSubmissions.has(acceptedKey(sessionKey, surfaceId, componentId))
  );
}

export function useA2UIFormSubmitted(
  surfaceId: string,
  componentId: string
): boolean {
  return useSyncExternalStore(
    (listener) => {
      submissionListeners.add(listener);
      return () => submissionListeners.delete(listener);
    },
    () => isA2UIFormSubmitted(surfaceId, componentId),
    () => false
  );
}

export function clearA2UIFormSubmissionState(sessionKey: string): void {
  let changed = false;
  for (const [surfaceId, owner] of surfaceSessions) {
    if (owner === sessionKey) {
      surfaceSessions.delete(surfaceId);
      changed = true;
    }
  }
  const prefix = `${sessionKey}\u0000`;
  for (const key of acceptedSubmissions.keys()) {
    if (key.startsWith(prefix)) {
      acceptedSubmissions.delete(key);
      changed = true;
    }
  }
  if (changed) notifySubmissionListeners();
}

export function clearAllA2UIFormSubmissionState(): void {
  const changed =
    stagedSubmissions.size > 0 ||
    surfaceSessions.size > 0 ||
    acceptedSubmissions.size > 0;
  stagedSubmissions.clear();
  surfaceSessions.clear();
  acceptedSubmissions.clear();
  if (changed) notifySubmissionListeners();
}
