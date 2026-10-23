import type { ReactNode } from "react";

export function UserMessageBubble({ children }: { children: ReactNode }) {
  return (
    <div className="aui-user-message-content peer bg-muted text-foreground rounded-xl px-4 py-2 wrap-break-word empty:hidden">
      {children}
    </div>
  );
}
