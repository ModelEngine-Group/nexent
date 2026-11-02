// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export type BranchMessageLike = {
  id: string;
  role: string;
};

/**
 * Derive the 1-based turn number that an assistant message answers.
 *
 * A turn is one user message plus its answer(s); the turn number therefore
 * equals the count of user messages from the thread start up to and including
 * the turn of the selected assistant message. The backend resolves the same
 * turn over its active (deduplicated) user rows, so both sides agree even
 * after refresh duplicates or regenerated answers. Returns null when the
 * message is missing from the list or no user message precedes it.
 */
export function computeBranchTurnIndex(
  messages: readonly BranchMessageLike[],
  assistantMessageId: string
): number | null {
  const position = messages.findIndex((m) => m.id === assistantMessageId);
  if (position < 0) return null;
  let turnIndex = 0;
  for (let index = 0; index <= position; index++) {
    if (messages[index].role === "user") turnIndex++;
  }
  return turnIndex >= 1 ? turnIndex : null;
}
