// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useRef, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import {
  CheckIcon,
  MessageSquareQuote,
  PencilIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  useAnnotationQuotePreview,
  type MessageAnnotation,
} from "../utils/message-annotations";

/** Hover grace period before the popover closes. */
const POPOVER_CLOSE_DELAY_MS = 150;

/**
 * Composer chip summarizing the pending message annotations.
 *
 * Renders nothing without annotations. Hovering (or focusing) the chip opens
 * the annotation list where each entry can be edited or deleted; the trailing
 * button clears every annotation at once.
 */
export const ComposerAnnotationChip: FC<{
  /** Pending annotations in creation order. */
  annotations: readonly MessageAnnotation[];
  /** Disables edit/delete/clear actions while a run is active. */
  disabled?: boolean;
  /** Saves an edited comment. */
  onEditComment: (id: string, comment: string) => void;
  /** Deletes a single annotation. */
  onRemove: (id: string) => void;
  /** Deletes every pending annotation. */
  onClear: () => void;
}> = ({ annotations, disabled, onEditComment, onRemove, onClear }) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const closeTimerRef = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(closeTimerRef.current), []);

  const openNow = useCallback(() => {
    window.clearTimeout(closeTimerRef.current);
    setOpen(true);
  }, []);

  const scheduleClose = useCallback(() => {
    // Keep the popover open while a comment is being edited so moving the
    // pointer towards the input cannot discard the draft.
    if (editingId) return;
    window.clearTimeout(closeTimerRef.current);
    closeTimerRef.current = window.setTimeout(
      () => setOpen(false),
      POPOVER_CLOSE_DELAY_MS
    );
  }, [editingId]);

  const startEdit = useCallback((annotation: MessageAnnotation) => {
    setEditingId(annotation.id);
    setEditValue(annotation.comment ?? "");
  }, []);

  const commitEdit = useCallback(() => {
    if (editingId) onEditComment(editingId, editValue.trim());
    setEditingId(null);
  }, [editValue, editingId, onEditComment]);

  const cancelEdit = useCallback(() => setEditingId(null), []);

  if (annotations.length === 0) return null;

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setEditingId(null);
      }}
    >
      <PopoverTrigger asChild>
        <span
          role="button"
          tabIndex={0}
          aria-label={t("chat.annotation.listTitle")}
          onMouseEnter={openNow}
          onMouseLeave={scheduleClose}
          onFocus={openNow}
          onBlur={scheduleClose}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              openNow();
            }
          }}
          className="inline-flex h-7 max-w-72 cursor-pointer items-center gap-1.5 rounded-md border border-[#e5e5e5] bg-[#f7f7f7] px-2 text-xs text-[#191919] dark:border-[#404040] dark:bg-[#2a2a2a] dark:text-[#e5e5e5]"
        >
          <MessageSquareQuote className="size-3.5 shrink-0" aria-hidden />
          <span className="truncate">
            {t("chat.annotation.chipLabel", { count: annotations.length })}
          </span>
          <button
            type="button"
            disabled={disabled}
            aria-label={t("chat.annotation.clearAnnotations")}
            title={t("chat.annotation.clearAnnotations")}
            onClick={(event) => {
              event.stopPropagation();
              setEditingId(null);
              setOpen(false);
              onClear();
            }}
            className="inline-flex size-4 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            <XIcon className="size-3" aria-hidden />
          </button>
        </span>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        onMouseEnter={openNow}
        onMouseLeave={scheduleClose}
        className="w-80 p-2"
      >
        <p className="mb-1.5 px-1 text-xs font-medium text-muted-foreground">
          {t("chat.annotation.listTitle")}
        </p>
        <ol className="flex flex-col gap-1">
          {annotations.map((annotation, index) => (
            <AnnotationListItem
              key={annotation.id}
              index={index + 1}
              annotation={annotation}
              editing={editingId === annotation.id}
              editValue={editValue}
              disabled={disabled}
              onEditValueChange={setEditValue}
              onEditStart={startEdit}
              onEditCommit={commitEdit}
              onEditCancel={cancelEdit}
              onRemove={onRemove}
            />
          ))}
        </ol>
      </PopoverContent>
    </Popover>
  );
};

const AnnotationListItem: FC<{
  index: number;
  annotation: MessageAnnotation;
  editing: boolean;
  editValue: string;
  disabled?: boolean;
  onEditValueChange: (value: string) => void;
  onEditStart: (annotation: MessageAnnotation) => void;
  onEditCommit: () => void;
  onEditCancel: () => void;
  onRemove: (id: string) => void;
}> = ({
  index,
  annotation,
  editing,
  editValue,
  disabled,
  onEditValueChange,
  onEditStart,
  onEditCommit,
  onEditCancel,
  onRemove,
}) => {
  const { t } = useTranslation();
  const quotePreview = useAnnotationQuotePreview(annotation);
  const editInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (editing) editInputRef.current?.focus();
  }, [editing]);

  if (editing) {
    return (
      <li className="flex items-center gap-1.5 rounded-md bg-muted/40 px-2 py-1.5">
        <span className="w-4 shrink-0 text-right text-xs text-muted-foreground">
          {index}.
        </span>
        <input
          ref={editInputRef}
          value={editValue}
          disabled={disabled}
          aria-label={t("chat.annotation.editPlaceholder")}
          placeholder={t("chat.annotation.editPlaceholder")}
          onChange={(event) => onEditValueChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              onEditCommit();
            } else if (event.key === "Escape") {
              event.preventDefault();
              onEditCancel();
            }
          }}
          className="h-7 min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
        />
        <button
          type="button"
          disabled={disabled}
          aria-label={t("chat.annotation.saveComment")}
          title={t("chat.annotation.saveComment")}
          onClick={onEditCommit}
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-primary hover:bg-accent disabled:opacity-50"
        >
          <CheckIcon className="size-3.5" aria-hidden />
        </button>
        <button
          type="button"
          disabled={disabled}
          aria-label={t("chat.annotation.cancelEdit")}
          title={t("chat.annotation.cancelEdit")}
          onClick={onEditCancel}
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent disabled:opacity-50"
        >
          <XIcon className="size-3.5" aria-hidden />
        </button>
      </li>
    );
  }

  return (
    <li className="group/annotation-item flex items-start gap-1.5 rounded-md px-2 py-1.5 hover:bg-muted/40">
      <span className="w-4 shrink-0 text-right text-xs leading-5 text-muted-foreground">
        {index}.
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs leading-5">
          <span className="text-muted-foreground">
            {t("chat.annotation.selectedTextLabel")}
            {t("chat.annotation.colon")}
          </span>
          {quotePreview}
        </p>
        {annotation.comment ? (
          <p className="truncate text-xs leading-5 text-muted-foreground">
            <span>{t("chat.annotation.commentLabel")}</span>
            {t("chat.annotation.colon")}
            {annotation.comment}
          </p>
        ) : null}
      </div>
      <span
        className={cn(
          "flex shrink-0 items-center gap-0.5 self-center opacity-0 transition-opacity group-hover/annotation-item:opacity-100 focus-within:opacity-100",
          disabled && "pointer-events-none"
        )}
      >
        <button
          type="button"
          disabled={disabled}
          aria-label={t("chat.annotation.editComment")}
          title={t("chat.annotation.editComment")}
          onClick={() => onEditStart(annotation)}
          className="inline-flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
        >
          <PencilIcon className="size-3.5" aria-hidden />
        </button>
        <button
          type="button"
          disabled={disabled}
          aria-label={t("chat.annotation.deleteAnnotation")}
          title={t("chat.annotation.deleteAnnotation")}
          onClick={() => onRemove(annotation.id)}
          className="inline-flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
        >
          <Trash2Icon className="size-3.5" aria-hidden />
        </button>
      </span>
    </li>
  );
};
