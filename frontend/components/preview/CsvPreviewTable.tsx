// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";
import { useState, type ReactNode, type UIEventHandler } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface CsvPreviewTableProps {
  columns: {
    key: string;
    dataIndex: string;
    title: ReactNode;
    width: number;
  }[];
  rows: Record<string, string>[];
  height: number;
  width: number;
  onScroll?: UIEventHandler<HTMLDivElement>;
}

/** Window large CSV previews without changing the streaming reader's contract. */
export function CsvPreviewTable({
  columns,
  rows,
  height,
  width,
  onScroll,
}: CsvPreviewTableProps) {
  const [scrollTop, setScrollTop] = useState(0);
  const rowHeight = 32;
  const viewport = Math.max(100, height);
  const start = Math.max(
    0,
    Math.min(
      Math.max(0, rows.length - Math.ceil(viewport / rowHeight)),
      Math.floor(scrollTop / rowHeight) - 8
    )
  );
  const end = Math.min(
    rows.length,
    start + Math.ceil(viewport / rowHeight) + 16
  );
  return (
    <div
      className="min-h-0 overflow-auto rounded-md border [&_[data-slot=table-container]]:overflow-visible"
      style={{ height: viewport }}
      onScroll={(event) => {
        setScrollTop(event.currentTarget.scrollTop);
        onScroll?.(event);
      }}
    >
      <Table style={{ minWidth: width }} aria-rowcount={rows.length + 1}>
        <TableHeader className="sticky top-0 z-10 bg-muted">
          <TableRow>
            {columns.map((column) => (
              <TableHead
                key={column.key}
                style={{ width: column.width, minWidth: column.width }}
              >
                {column.title}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {start > 0 && (
            <TableRow aria-hidden="true">
              <TableCell
                colSpan={columns.length}
                className="p-0"
                style={{ height: start * rowHeight }}
              />
            </TableRow>
          )}
          {rows.slice(start, end).map((row, offset) => (
            <TableRow key={row._key} aria-rowindex={start + offset + 2}>
              {columns.map((column) => (
                <TableCell
                  key={column.key}
                  className="p-0"
                  style={{ maxWidth: column.width }}
                >
                  <div
                    className="h-[31px] truncate px-3 leading-[31px]"
                    title={row[column.dataIndex]}
                  >
                    {row[column.dataIndex]}
                  </div>
                </TableCell>
              ))}
            </TableRow>
          ))}
          {end < rows.length && (
            <TableRow aria-hidden="true">
              <TableCell
                colSpan={columns.length}
                className="p-0"
                style={{ height: (rows.length - end) * rowHeight }}
              />
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
