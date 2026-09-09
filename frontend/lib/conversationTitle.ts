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
