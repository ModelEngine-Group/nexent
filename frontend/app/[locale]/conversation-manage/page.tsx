"use client";

import { Flex } from "antd";
import { ConversationManagePage } from "./components/ConversationManagePage";

/**
 * Conversation Management page - supports filtering conversations by date range, agent, and keyword.
 */
export default function ConversationManagePageWrapper() {
  return (
    <Flex
      vertical
      style={{ width: "100%", height: "100%" }}
      className="h-full w-full overflow-hidden p-6"
    >
      <ConversationManagePage />
    </Flex>
  );
}