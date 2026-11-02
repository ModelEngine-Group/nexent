// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { memo, useMemo, type ComponentProps, type FC } from "react";
import { useTranslation } from "react-i18next";
import { useAuiState } from "@assistant-ui/react";
import { MessageSquareQuote } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fromMessageAnnotationWireItems,
  type MessageAnnotationWireItem,
} from "../utils/message-annotations";

/**
 * Read-only annotation cards rendered on a user message bubble.
 *
 * One card per attached reply annotation: the quoted excerpt, an optional
 * comment line and the source reply excerpt. Data comes from the message's
 * structured `metadata.custom.annotations` (set by the optimistic append on
 * send and restored from the persisted history unit on reload), so the
 * cards survive page refreshes just like the model-facing context does.
 */
export const MessageAnnotationCards: FC<
  {
    /** Overrides the message metadata (used by unit tests). */
    annotations?: readonly unknown[];
  } & ComponentProps<"div">
> = memo(function MessageAnnotationCards({
  annotations: annotationsProp,
  className,
  ...props
}) {
  const rawAnnotations = useAuiState((state) =>
    state.message?.role === "user"
      ? (
          state.message.metadata as
            { custom?: { annotations?: unknown[] } } | undefined
        )?.custom?.annotations
      : undefined,
  );
  const items = useMemo(
    () => fromMessageAnnotationWireItems(annotationsProp ?? rawAnnotations),
    [annotationsProp, rawAnnotations],
  );
  if (items.length === 0) return null;

  return (
    <div
      data-slot="aui_message-annotation-cards"
      className={cn("flex flex-col gap-2", className)}
      {...props}
    >
      {items.map((item) => (
        <AnnotationCard
          key={`${item.quoted_text}-${item.source_excerpt ?? ""}`}
          item={item}
        />
      ))}
    </div>
  );
});

const AnnotationCard: FC<{ item: MessageAnnotationWireItem }> = ({ item }) => {
  const { t } = useTranslation();
  return (
    <div
      data-slot="aui_message-annotation-card"
      className="border-muted-foreground/30 text-muted-foreground mb-1 flex items-start gap-2 border-l-2 pl-2 text-sm italic"
    >
      <MessageSquareQuote className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="whitespace-pre-wrap break-words">{item.quoted_text}</p>
        {item.comment ? (
          <p className="text-foreground/80 not-italic">
            {t("chat.annotation.commentLabel")}
            {t("chat.annotation.colon")}
            {item.comment}
          </p>
        ) : null}
        {item.source_excerpt ? (
          <p className="text-muted-foreground/80 not-italic text-xs">
            {t("chat.annotation.cardSourceLabel", {
              excerpt: item.source_excerpt,
            })}
          </p>
        ) : null}
      </div>
    </div>
  );
};
