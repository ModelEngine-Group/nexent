// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useRef, useState, type ThHTMLAttributes } from "react";

export interface AgentTableHeaderProps extends ThHTMLAttributes<HTMLTableCellElement> {
  resizeWidth?: number;
  minWidth?: number;
  resizeLabel?: string;
  resizeFromStart?: boolean;
  onResizeWidth?: (width: number) => void;
}

export default function AgentTableHeader({
  children,
  resizeWidth,
  minWidth = 100,
  resizeLabel,
  resizeFromStart = false,
  onResizeWidth,
  ...props
}: AgentTableHeaderProps) {
  const drag = useRef<{ x: number; width: number; pointerId: number } | null>(
    null
  );
  const [dragging, setDragging] = useState(false);
  const clamp = (width: number) =>
    Math.round(Math.min(4096, Math.max(minWidth, width)));

  return (
    <th {...props}>
      {children}
      {resizeWidth !== undefined && onResizeWidth ? (
        <span
          role="separator"
          aria-orientation="vertical"
          aria-label={resizeLabel}
          aria-valuemin={minWidth}
          aria-valuemax={4096}
          aria-valuenow={Math.round(resizeWidth)}
          tabIndex={0}
          title={resizeLabel}
          className={`agent-table-resize-handle ${resizeFromStart ? "is-start" : ""} ${dragging ? "is-dragging" : ""}`}
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => {
            if (event.button !== 0 || !event.isPrimary) return;
            event.preventDefault();
            event.stopPropagation();
            drag.current = {
              x: event.clientX,
              width: resizeWidth,
              pointerId: event.pointerId,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
            setDragging(true);
          }}
          onPointerMove={(event) => {
            const start = drag.current;
            if (!start || event.pointerId !== start.pointerId) return;
            const delta =
              (event.clientX - start.x) * (resizeFromStart ? -1 : 1);
            onResizeWidth(clamp(start.width + delta));
          }}
          onPointerUp={(event) => {
            if (drag.current?.pointerId !== event.pointerId) return;
            drag.current = null;
            setDragging(false);
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              event.currentTarget.releasePointerCapture(event.pointerId);
            }
          }}
          onPointerCancel={() => {
            drag.current = null;
            setDragging(false);
          }}
          onLostPointerCapture={() => {
            drag.current = null;
            setDragging(false);
          }}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            event.stopPropagation();
            onResizeWidth(
              clamp(resizeWidth + (event.key === "ArrowRight" ? 16 : -16))
            );
          }}
        />
      ) : null}
    </th>
  );
}
