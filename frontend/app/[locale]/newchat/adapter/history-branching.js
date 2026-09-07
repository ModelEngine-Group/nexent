/** @typedef {import("@/types/conversation").ApiMessage} ApiMessage */

/**
 * Return whether two user rows represent the same logical message boundary.
 * Separate turns may contain identical text, while regenerated branches reuse
 * the same message index.
 *
 * @param {ApiMessage} left
 * @param {ApiMessage} right
 */
const areSameUserMessages = (left, right) => {
  const bothHaveIndex =
    typeof left.message_index === "number" &&
    typeof right.message_index === "number";
  const sameLogicalIndex = bothHaveIndex
    ? left.message_index === right.message_index
    : left.message_index == null && right.message_index == null;

  return (
    left.role === "user" &&
    right.role === "user" &&
    sameLogicalIndex &&
    JSON.stringify(left.message) === JSON.stringify(right.message) &&
    JSON.stringify(left.minio_files ?? []) ===
      JSON.stringify(right.minio_files ?? [])
  );
};

/**
 * Collapse refresh-generated duplicate user rows while keeping identical text
 * from separate message indexes as independent conversation turns.
 *
 * @param {ApiMessage[]} messages
 * @returns {ApiMessage[]}
 */
export const collapseRefreshUserMessages = (messages) => {
  /** @type {ApiMessage[]} */
  const collapsed = [];
  /** @type {ApiMessage | undefined} */
  let activeUserMessage;

  for (const message of messages) {
    if (message.role !== "user") {
      collapsed.push(message);
      continue;
    }

    if (activeUserMessage && areSameUserMessages(activeUserMessage, message)) {
      continue;
    }

    collapsed.push(message);
    activeUserMessage = message;
  }

  return collapsed;
};
