export interface GenerateConversationTitleParams {
  conversation_id: number;
  question: string;
  model_id?: number;
}

export const createConversationTitleRequest = (
  conversationId: number,
  question: string,
  modelId: number | null
): GenerateConversationTitleParams => ({
  conversation_id: conversationId,
  question,
  ...(modelId !== null ? { model_id: modelId } : {}),
});

/** Invalidate delayed automatic results after a successful explicit rename. */
export class ConversationTitleGuard {
  private readonly revisions = new Map<string, number>();

  capture(threadId: string): number {
    return this.revisions.get(threadId) ?? 0;
  }

  renamed(threadId: string): void {
    this.revisions.set(threadId, this.capture(threadId) + 1);
  }

  isCurrent(threadId: string, revision: number): boolean {
    return this.capture(threadId) === revision;
  }
}
