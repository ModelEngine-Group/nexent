"use client";

import React, { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { AIDP_MIN_COLUMN_WIDTH } from "@/lib/aidpKnowledgeColumnWidths";
import styles from "./AidpKnowledgeVisuals.module.css";

export interface AidpResizableTitleProps extends Omit<
  React.ThHTMLAttributes<HTMLTableCellElement>,
  "onResize"
> {
  width?: number;
  maxWidth?: number;
  onResize?: (delta: number, widths: Record<string, number>) => void;
}

function measureWidths(handle: HTMLElement): Record<string, number> {
  const widths: Record<string, number> = {};
  handle
    .closest("table")
    ?.querySelectorAll<HTMLTableCellElement>("th[data-column-key]")
    .forEach((cell) => {
      if (cell.dataset.columnKey)
        widths[cell.dataset.columnKey] = cell.getBoundingClientRect().width;
    });
  return widths;
}

const AidpResizableTitle: React.FC<AidpResizableTitleProps> = ({
  width,
  maxWidth,
  onResize,
  children,
  ...rest
}) => {
  const { t } = useTranslation();
  const drag = useRef<{
    x: number;
    widths: Record<string, number>;
    cursor: string;
    userSelect: string;
  } | null>(null);
  const finishDrag = () => {
    if (!drag.current) return;
    document.body.style.cursor = drag.current.cursor;
    document.body.style.userSelect = drag.current.userSelect;
    drag.current = null;
  };
  useEffect(() => finishDrag, []);
  const isFixedColumn = Boolean(rest.className?.includes("ant-table-cell-fix"));

  return (
    <th
      {...rest}
      style={{
        ...rest.style,
        width,
        ...(isFixedColumn ? {} : { position: "relative" }),
      }}
    >
      {children}
      {onResize && (
        <div
          role="separator"
          tabIndex={0}
          aria-orientation="vertical"
          aria-label={t("aidpKnowledge.resizeColumn")}
          aria-valuemin={AIDP_MIN_COLUMN_WIDTH}
          aria-valuemax={maxWidth}
          aria-valuenow={width}
          className={styles.columnResizeHandle}
          onPointerDown={(event) => {
            if (event.button !== 0 || !event.isPrimary) return;
            event.preventDefault();
            event.stopPropagation();
            drag.current = {
              x: event.clientX,
              widths: measureWidths(event.currentTarget),
              cursor: document.body.style.cursor,
              userSelect: document.body.style.userSelect,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";
          }}
          onPointerMove={(event) => {
            if (!drag.current) return;
            event.preventDefault();
            onResize(event.clientX - drag.current.x, drag.current.widths);
          }}
          onPointerUp={finishDrag}
          onPointerCancel={finishDrag}
          onLostPointerCapture={finishDrag}
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            event.stopPropagation();
            onResize(
              event.key === "ArrowRight" ? 8 : -8,
              measureWidths(event.currentTarget)
            );
          }}
        />
      )}
    </th>
  );
};

export default AidpResizableTitle;
