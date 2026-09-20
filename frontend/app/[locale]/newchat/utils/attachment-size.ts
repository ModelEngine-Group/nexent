export const NEW_CHAT_MAX_FILE_SIZE_MB = 10;
export const NEW_CHAT_MAX_FILE_COUNT = 50;

const NEW_CHAT_MAX_FILE_SIZE_BYTES = NEW_CHAT_MAX_FILE_SIZE_MB * 1024 * 1024;

export const isNewChatFileTooLarge = (size: number): boolean =>
  size > NEW_CHAT_MAX_FILE_SIZE_BYTES;

export const canAddNewChatAttachment = (attachmentCount: number): boolean =>
  attachmentCount < NEW_CHAT_MAX_FILE_COUNT;
