const listeners = new Set<(modelId: number) => void>();

/** Notify mounted controllers only; no persistent model configuration changes. */
export function rejectModelSelection(modelId: number) {
  for (const listener of listeners) listener(modelId);
}

export function subscribeRejectedSelection(
  listener: (modelId: number) => void
) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
