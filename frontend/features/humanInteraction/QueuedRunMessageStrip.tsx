"use client";

import { useState } from "react";
import { CornerDownRight, ListStart, Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useRunMessageQueueContext } from "./useRunMessageQueue";

export function QueuedRunMessageStrip() {
  const queue = useRunMessageQueueContext();
  const { i18n } = useTranslation();
  const zh = i18n.language.startsWith("zh");
  const [draft, setDraft] = useState(queue?.entry?.text ?? "");
  const entry = queue?.entry;
  if (!queue || !entry) return null;
  const locked = entry.status === "delivering";
  const immutable = locked || entry.status === "uncertain";
  const editing = entry.status === "editing";

  return (
    <section
      data-slot="queued-run-message"
      aria-label={zh ? "排队消息" : "Queued message"}
      className="mx-3 -mb-3 rounded-t-2xl border border-border/70 bg-muted/20 px-3 pb-5 pt-2 text-xs shadow-sm"
    >
      <div className="flex min-w-0 items-center gap-2">
        <ListStart className="size-3.5 shrink-0 text-muted-foreground" />
        <span
          className="min-w-0 flex-1 truncate text-foreground"
          title={entry.text}
        >
          {entry.text}
        </span>
        <div className="flex shrink-0 items-center gap-0.5 text-muted-foreground">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 gap-1 px-2 text-xs"
            disabled={
              locked ||
              editing ||
              ((queue.active || entry.status === "uncertain") &&
                !queue.canGuide)
            }
            onClick={() =>
              queue.active || entry.status === "uncertain"
                ? void queue.guide()
                : queue.sendNext()
            }
          >
            <CornerDownRight className="size-3" />
            {entry.status === "delivering"
              ? zh
                ? "提交中"
                : "Sending"
              : entry.status === "uncertain"
                ? zh
                  ? "重试引导"
                  : "Retry steering"
                : queue.active
                  ? zh
                    ? "引导"
                    : "Steer"
                  : zh
                    ? "发送"
                    : "Send"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6"
            disabled={immutable}
            aria-label={zh ? "删除排队消息" : "Delete queued message"}
            onClick={() => queue.update({ type: "delete" })}
          >
            <Trash2 className="size-3" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6"
            disabled={immutable || editing}
            aria-label={zh ? "修改排队消息" : "Edit queued message"}
            onClick={() => {
              setDraft(entry.text);
              queue.update({ type: "edit" });
            }}
          >
            <Pencil className="size-3" />
          </Button>
        </div>
      </div>
      {editing ? (
        <div className="mt-2 space-y-2">
          <textarea
            autoFocus
            rows={2}
            maxLength={8000}
            value={draft}
            aria-label={zh ? "修改排队消息内容" : "Edit queued message text"}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Escape") queue.update({ type: "cancel-edit" });
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                queue.update({ type: "save", text: draft });
              }
            }}
            className="w-full resize-y rounded-lg border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => queue.update({ type: "cancel-edit" })}
            >
              {zh ? "取消" : "Cancel"}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!draft.trim()}
              onClick={() => queue.update({ type: "save", text: draft })}
            >
              {zh ? "保存" : "Save"}
            </Button>
          </div>
        </div>
      ) : null}
      {entry.error ? (
        <p role="alert" className="mt-2 text-destructive">
          {entry.error}
        </p>
      ) : null}
    </section>
  );
}
