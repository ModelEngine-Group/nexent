"use client";

import { UserMessageBubble } from "@/components/interaction/user-message-bubble";
import { formatMessageTime } from "@/lib/messageDate";
import { parseGuidanceMessage } from "./guidanceMessage";

export function UserGuidanceMessage({ data }: { data: unknown }) {
  const message = parseGuidanceMessage(data);
  if (!message) return null;
  const displayTime = formatMessageTime(new Date(message.created_at));
  return (
    <div
      data-slot="user-guidance-message"
      data-role="user"
      data-request-id={message.request_id}
      className="my-4 flex w-full justify-end"
    >
      <div className="flex min-w-0 max-w-[calc(100%_-_72px)] flex-col gap-2">
        <UserMessageBubble>
          <span className="whitespace-pre-wrap">{message.text}</span>
        </UserMessageBubble>
        {displayTime && (
          <time
            dateTime={message.created_at}
            className="self-end text-xs text-muted-foreground"
          >
            {displayTime}
          </time>
        )}
      </div>
    </div>
  );
}
