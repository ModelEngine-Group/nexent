// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { Popover } from "antd";

const chipClassName =
  "block max-w-[120px] shrink-0 truncate rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200";

export function AgentCardTags({ labels }: { labels: string[] }) {
  const rowRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const [visibleCount, setVisibleCount] = useState(labels.length);
  const labelKey = JSON.stringify(labels);

  useLayoutEffect(() => {
    const row = rowRef.current;
    const measure = measureRef.current;
    if (!row || !measure) return;
    const update = () => {
      if (row.clientWidth === 0) return;
      const chips = Array.from(measure.children) as HTMLElement[];
      const widths = chips
        .slice(0, -1)
        .map((chip) => chip.getBoundingClientRect().width);
      const gap = 8;
      const fullWidth =
        widths.reduce((sum, width) => sum + width, 0) +
        Math.max(0, widths.length - 1) * gap;
      if (fullWidth <= row.clientWidth) {
        setVisibleCount(widths.length);
        return;
      }
      const moreWidth = chips.at(-1)?.getBoundingClientRect().width ?? 0;
      let usedWidth = moreWidth;
      let count = 0;
      for (const width of widths) {
        if (usedWidth + gap + width > row.clientWidth) break;
        usedWidth += gap + width;
        count += 1;
      }
      setVisibleCount(count);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(row);
    observer.observe(measure);
    return () => observer.disconnect();
  }, [labelKey]);

  if (labels.length === 0) return null;
  const count = Math.min(visibleCount, labels.length);
  const hiddenCount = labels.length - count;

  return (
    <div
      ref={rowRef}
      className="pointer-events-auto relative z-10 flex h-6 w-full min-w-0 items-center gap-2 overflow-hidden"
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
    >
      <div
        ref={measureRef}
        aria-hidden="true"
        className="pointer-events-none invisible absolute inset-x-0 flex w-full items-center gap-2"
      >
        {labels.map((label, index) => (
          <span key={index} className={chipClassName}>
            {label}
          </span>
        ))}
        <span className={chipClassName}>+{labels.length}</span>
      </div>
      {labels.slice(0, count).map((label, index) => (
        <span key={index} title={label} className={chipClassName}>
          {label}
        </span>
      ))}
      {hiddenCount > 0 ? (
        <Popover
          trigger={["hover", "click", "focus"]}
          placement="topLeft"
          content={
            <div
              className="flex max-h-64 max-w-[360px] flex-wrap gap-2 overflow-y-auto"
              onClick={(event) => event.stopPropagation()}
            >
              {labels.map((label, index) => (
                <span
                  key={index}
                  className="max-w-full break-words rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700 [overflow-wrap:anywhere] dark:bg-slate-800 dark:text-slate-200"
                >
                  {label}
                </span>
              ))}
            </div>
          }
        >
          <button
            type="button"
            className={`${chipClassName} cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500`}
          >
            +{hiddenCount}
          </button>
        </Popover>
      ) : null}
    </div>
  );
}
