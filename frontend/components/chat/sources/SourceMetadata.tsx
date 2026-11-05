// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/common/Popover";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { XIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { JsonObject, JsonValue } from "@/types/source";
import styles from "@/components/chat/sources/SourceMetadata.module.css";

interface SourceMetadataProps {
  metadata?: JsonObject;
}

function isStructured(value: JsonValue): value is JsonObject | JsonValue[] {
  return value !== null && typeof value === "object";
}

function scalarText(value: JsonValue): string {
  return value === "" ? '""' : String(value);
}

function entriesOf(value: JsonObject | JsonValue[]): [string, JsonValue][] {
  return Array.isArray(value)
    ? value.map((entry, index) => [`[${index}]`, entry])
    : Object.keys(value)
        .sort()
        .map((key) => [key, value[key]]);
}

function MetadataGroup({
  name,
  value,
}: {
  name: string;
  value: JsonObject | JsonValue[];
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <details
      className={styles.group}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>{name}</summary>
      {expanded && (
        <div className={styles.children}>
          {Object.keys(value).length ? (
            <MetadataProperties value={value} />
          ) : Array.isArray(value) ? (
            "[]"
          ) : (
            "{}"
          )}
        </div>
      )}
    </details>
  );
}

function MetadataProperties({ value }: { value: JsonObject | JsonValue[] }) {
  return (
    <div className={styles.properties}>
      {entriesOf(value).map(([key, entry]) =>
        isStructured(entry) ? (
          <MetadataGroup key={key} name={key} value={entry} />
        ) : (
          <dl key={key} className={styles.property}>
            <dt>{key}</dt>
            <dd>{scalarText(entry)}</dd>
          </dl>
        )
      )}
    </div>
  );
}

const MetadataJson = memo(function MetadataJson({
  metadata,
}: {
  metadata: JsonObject;
}) {
  const text = useMemo(() => JSON.stringify(metadata, null, 2), [metadata]);
  return <pre className={styles.json}>{text}</pre>;
});

function MetadataDetails({
  metadata,
  popoverRef,
  onClose,
}: {
  metadata: JsonObject;
  popoverRef: RefObject<HTMLDivElement | null>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className={styles.popover}
      ref={popoverRef}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      <div className={styles.heading}>
        <span>{t("chat.sources.attributes")}</span>
        <button
          type="button"
          aria-label={t("chat.sources.closeAttributes")}
          onClick={onClose}
        >
          <XIcon className="size-4" />
        </button>
      </div>
      <Tabs defaultValue="properties">
        <TabsList>
          <TabsTrigger value="properties">
            {t("chat.sources.properties")}
          </TabsTrigger>
          <TabsTrigger value="json">{t("chat.sources.rawJson")}</TabsTrigger>
        </TabsList>
        <TabsContent value="properties">
          <MetadataProperties value={metadata} />
        </TabsContent>
        <TabsContent value="json">
          <MetadataJson metadata={metadata} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Per-hit raw-key chips; hover, focus and click reveal the complete snapshot. */
export const SourceMetadata = memo(function SourceMetadata({
  metadata,
}: SourceMetadataProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelHoverClose = () => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
  };
  const leave = () => {
    cancelHoverClose();
    hoverTimer.current = setTimeout(() => {
      if (!pinned) setOpen(false);
    }, 200);
  };
  useEffect(
    () => () => {
      if (hoverTimer.current) clearTimeout(hoverTimer.current);
    },
    []
  );
  const popoverRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => {
    if (popoverRef.current?.contains(document.activeElement))
      triggerRef.current?.focus();
    setPinned(false);
    setOpen(false);
  }, []);
  useEffect(() => {
    if (!pinned) return;
    const dismiss = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        triggerRef.current?.contains(target) ||
        popoverRef.current?.contains(target)
      )
        return;
      setPinned(false);
      setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [pinned]);
  const entries = useMemo(
    () => (metadata ? entriesOf(metadata) : []),
    [metadata]
  );
  const labels = useMemo(
    () =>
      entries.map(([key, value]) => {
        if (!isStructured(value)) return `${key}：${scalarText(value)}`;
        const count = Object.keys(value).length;
        const countLabel = t("chat.sources.attributeCount", { count });
        const summary = Array.isArray(value)
          ? count
            ? `[${countLabel}]`
            : "[]"
          : count
            ? `{${countLabel}}`
            : "{}";
        return `${key}：${summary}`;
      }),
    [entries, t]
  );

  if (!metadata || entries.length === 0) return null;

  return (
    <div
      className={styles.root}
      data-source-metadata
      onClick={(event) => event.stopPropagation()}
    >
      <Popover
        open={open}
        onOpenChange={(next) => {
          if (!pinned) setOpen(next);
        }}
      >
        <PopoverAnchor asChild>
          <button
            type="button"
            ref={triggerRef}
            onMouseEnter={() => {
              cancelHoverClose();
              setOpen(true);
            }}
            onMouseLeave={leave}
            onFocus={() => {
              cancelHoverClose();
              setOpen(true);
            }}
            onBlur={(event) => {
              if (
                !pinned &&
                !popoverRef.current?.contains(event.relatedTarget as Node)
              )
                setOpen(false);
            }}
            className={styles.trigger}
            aria-label={t("chat.sources.showAttributes")}
            aria-expanded={open}
            aria-haspopup="dialog"
            onClick={(event) => {
              if (pinned) {
                close();
                return;
              }
              setPinned(true);
              setOpen(true);
              if (event.detail === 0)
                requestAnimationFrame(() =>
                  popoverRef.current
                    ?.querySelector<HTMLButtonElement>("button")
                    ?.focus()
                );
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") close();
            }}
          >
            <span className={styles.chips}>
              {labels.map((label, index) => (
                <span key={entries[index][0]} className={styles.chip}>
                  {label}
                </span>
              ))}
            </span>
          </button>
        </PopoverAnchor>
        <PopoverContent
          aria-label={t("chat.sources.attributes")}
          side="bottom"
          align="start"
          className="z-[var(--ui-layer-popover)] w-auto max-w-[calc(100vw-2rem)]"
          onMouseEnter={cancelHoverClose}
          onMouseLeave={leave}
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
        >
          <MetadataDetails
            metadata={metadata}
            popoverRef={popoverRef}
            onClose={close}
          />
        </PopoverContent>
      </Popover>
    </div>
  );
});
