"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Popover, Tabs } from "antd";
import { XIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { JsonObject, JsonValue } from "@/types/source";
import styles from "./sourceMetadata.module.css";

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

function MetadataProperties({ value }: { value: JsonObject | JsonValue[] }) {
  return (
    <div className={styles.properties}>
      {entriesOf(value).map(([key, entry]) =>
        isStructured(entry) ? (
          <details key={key} className={styles.group}>
            <summary>{key}</summary>
            <div className={styles.children}>
              {Object.keys(entry).length ? (
                <MetadataProperties value={entry} />
              ) : Array.isArray(entry) ? (
                "[]"
              ) : (
                "{}"
              )}
            </div>
          </details>
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

/** Per-hit raw-key chips; hover, focus and click reveal the complete snapshot. */
export function SourceMetadata({ metadata }: SourceMetadataProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [visibleCount, setVisibleCount] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const close = () => {
    if (popoverRef.current?.contains(document.activeElement))
      triggerRef.current?.focus();
    setPinned(false);
    setOpen(false);
  };
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

  useLayoutEffect(() => {
    const trigger = triggerRef.current;
    const measure = measureRef.current;
    if (!trigger || !measure) return;
    const update = () => {
      const width = trigger.clientWidth;
      if (!width) return;
      const children = Array.from(measure.children) as HTMLElement[];
      const overflow = children[labels.length];
      const widths = children
        .slice(0, labels.length)
        .map((child) => child.getBoundingClientRect().width);
      const fits = (count: number) => {
        const sizes = widths.slice(0, count);
        if (count < labels.length) {
          overflow.textContent = `+${labels.length - count}`;
          sizes.push(overflow.getBoundingClientRect().width);
        }
        let rows = 1,
          used = 0;
        for (const size of sizes) {
          if (used && used + 5 + size > width) {
            rows++;
            used = 0;
          }
          used += (used ? 5 : 0) + size;
        }
        return rows <= 2;
      };
      let count = labels.length;
      while (count > 0 && !fits(count)) count--;
      setVisibleCount(count);
    };
    update();
    let active = true;
    document.fonts?.ready.then(() => {
      if (active) update();
    });
    const observer = new ResizeObserver(update);
    observer.observe(trigger);
    return () => {
      active = false;
      observer.disconnect();
    };
  }, [labels]);

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
        trigger={["hover", "focus"]}
        placement="bottomLeft"
        mouseEnterDelay={0.15}
        mouseLeaveDelay={0.2}
        content={
          <div
            className={styles.popover}
            ref={popoverRef}
            role="dialog"
            aria-label={t("chat.sources.attributes")}
            onKeyDown={(event) => {
              if (event.key === "Escape") close();
            }}
          >
            <div className={styles.heading}>
              <span>{t("chat.sources.attributes")}</span>
              <button
                type="button"
                aria-label={t("chat.sources.closeAttributes")}
                onClick={close}
              >
                <XIcon className="size-4" />
              </button>
            </div>
            <Tabs
              size="small"
              items={[
                {
                  key: "properties",
                  label: t("chat.sources.properties"),
                  children: <MetadataProperties value={metadata} />,
                },
                {
                  key: "json",
                  label: t("chat.sources.rawJson"),
                  children: (
                    <pre className={styles.json}>
                      {JSON.stringify(metadata, null, 2)}
                    </pre>
                  ),
                },
              ]}
            />
          </div>
        }
      >
        <button
          type="button"
          ref={triggerRef}
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
            {labels.slice(0, visibleCount).map((label, index) => (
              <span key={entries[index][0]} className={styles.chip}>
                {label}
              </span>
            ))}
            {visibleCount < labels.length && (
              <span className={styles.chip}>
                +{labels.length - visibleCount}
              </span>
            )}
          </span>
        </button>
      </Popover>
      <div className={styles.measure} ref={measureRef} aria-hidden="true">
        {labels.map((label, index) => (
          <span key={entries[index][0]} className={styles.chip}>
            {label}
          </span>
        ))}
        <span className={styles.chip}>+{labels.length}</span>
      </div>
    </div>
  );
}
