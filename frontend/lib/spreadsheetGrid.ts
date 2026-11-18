// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Worksheet } from "exceljs";

/** Rows and columns rendered per sheet before the preview is truncated. */
export const XLSX_MAX_ROWS_PER_SHEET = 300;
export const XLSX_MAX_COLUMNS_PER_SHEET = 40;

export interface SheetCell {
  text: string;
  colSpan: number;
  rowSpan: number;
  style?: {
    fontFamily?: string;
    fontSize?: number;
    fontWeight?: number;
    fontStyle?: string;
    color?: string;
    backgroundColor?: string;
    textAlign?: "left" | "center" | "right";
  };
}

export interface SheetGrid {
  name: string;
  rows: (SheetCell | null)[][];
  truncated: boolean;
  columnWidths?: number[];
  rowHeights?: number[];
}

const columnIndexFromLetters = (letters: string): number => {
  let index = 0;
  for (const letter of letters.toUpperCase()) {
    index = index * 26 + (letter.charCodeAt(0) - 64);
  }
  return index - 1;
};

/** Build the spreadsheet column label for a zero-based index: 0 -> A, 26 -> AA. */
export const columnIndexToLetters = (index: number): string => {
  let label = "";
  let remaining = index;
  do {
    label = String.fromCharCode(65 + (remaining % 26)) + label;
    remaining = Math.floor(remaining / 26) - 1;
  } while (remaining >= 0);
  return label;
};

/** Expand an `A1:C3` reference into zero-based bounds. */
const parseRange = (
  reference: string
): { top: number; left: number; bottom: number; right: number } | null => {
  const match = /^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$/i.exec(reference.trim());
  if (!match) {
    return null;
  }
  const [, startColumn, startRow, endColumn, endRow] = match;
  return {
    left: columnIndexFromLetters(startColumn),
    top: Number.parseInt(startRow, 10) - 1,
    right: columnIndexFromLetters(endColumn ?? startColumn),
    bottom: Number.parseInt(endRow ?? startRow, 10) - 1,
  };
};

/**
 * Build a display grid for one worksheet, collapsing merged ranges.
 *
 * ExcelJS exposes two different sizes per axis: `rowCount` is the *number of the
 * last used row* (likewise `columnCount` for the last used column), while
 * `actualRowCount` only counts the rows that hold data. A sheet whose single
 * value sits in A10 therefore reports `rowCount === 10` but
 * `actualRowCount === 1`: sizing the grid from the latter renders one row, drops
 * everything below it, and reports the grid as untruncated, so the missing rows
 * are invisible. The last-used numbers are the row/column bounds the preview
 * needs; empty rows between them are kept so the row numbers stay addressable.
 */
export const buildSheetGrid = (worksheet: Worksheet): SheetGrid => {
  const lastRowNumber = worksheet.rowCount || 0;
  const lastColumnNumber = worksheet.columnCount || 0;
  const rowCount = Math.min(lastRowNumber, XLSX_MAX_ROWS_PER_SHEET);
  const columnCount = Math.min(lastColumnNumber, XLSX_MAX_COLUMNS_PER_SHEET);

  const rows: (SheetCell | null)[][] = [];
  for (let row = 0; row < rowCount; row += 1) {
    rows.push(new Array<SheetCell | null>(columnCount).fill(null));
  }

  const merges = (worksheet.model?.merges ?? [])
    .map((range) => parseRange(range))
    .filter((range): range is NonNullable<typeof range> => range !== null);

  for (const range of merges) {
    if (range.top >= rowCount || range.left >= columnCount) {
      continue;
    }
    // Merged ranges outside the rendered window are clipped so the table never
    // claims a span the viewport does not contain.
    rows[range.top][range.left] = {
      // `cell.text` applies the number/date format the document declares.
      text: worksheet.getCell(range.top + 1, range.left + 1).text,
      rowSpan: Math.min(range.bottom, rowCount - 1) - range.top + 1,
      colSpan: Math.min(range.right, columnCount - 1) - range.left + 1,
    };
    for (
      let row = range.top;
      row <= Math.min(range.bottom, rowCount - 1);
      row += 1
    ) {
      for (
        let column = range.left;
        column <= Math.min(range.right, columnCount - 1);
        column += 1
      ) {
        if (row !== range.top || column !== range.left) {
          rows[row][column] = null;
        }
      }
    }
  }

  for (let row = 0; row < rowCount; row += 1) {
    for (let column = 0; column < columnCount; column += 1) {
      if (rows[row][column] !== null) {
        continue;
      }
      const cell = worksheet.getCell(row + 1, column + 1);
      if (
        cell.isMerged &&
        cell.master &&
        cell.master.address !== cell.address
      ) {
        // Continuation of a merge whose anchor sits outside the window.
        rows[row][column] = null;
        continue;
      }
      rows[row][column] = {
        text: cell.text,
        colSpan: 1,
        rowSpan: 1,
      };
    }
  }

  for (let row = 0; row < rowCount; row += 1) {
    for (let column = 0; column < columnCount; column += 1) {
      const target = rows[row][column];
      if (!target) continue;
      const cell = worksheet.getCell(row + 1, column + 1);
      const style: NonNullable<SheetCell["style"]> = {};
      if (cell.font?.name)
        style.fontFamily = `${JSON.stringify(cell.font.name)}, "Microsoft YaHei", sans-serif`;
      if (cell.font?.size) style.fontSize = (cell.font.size * 4) / 3;
      if (cell.font?.bold) style.fontWeight = 600;
      if (cell.font?.italic) style.fontStyle = "italic";
      if (cell.font?.color?.argb)
        style.color = `#${cell.font.color.argb.slice(-6)}`;
      if (
        cell.fill?.type === "pattern" &&
        cell.fill.pattern === "solid" &&
        cell.fill.fgColor?.argb
      ) {
        style.backgroundColor = `#${cell.fill.fgColor.argb.slice(-6)}`;
      }
      if (
        ["left", "center", "right"].includes(cell.alignment?.horizontal ?? "")
      ) {
        style.textAlign = cell.alignment.horizontal as
          "left" | "center" | "right";
      }
      if (Object.keys(style).length) target.style = style;
    }
  }

  return {
    name: worksheet.name,
    rows,
    truncated: lastRowNumber > rowCount || lastColumnNumber > columnCount,
    columnWidths: Array.from({ length: columnCount }, (_, index) =>
      Math.max(80, (worksheet.getColumn(index + 1).width ?? 16) * 7 + 5)
    ),
    rowHeights: Array.from({ length: rowCount }, (_, index) =>
      Math.max(30, ((worksheet.getRow(index + 1).height ?? 22.5) * 4) / 3)
    ),
  };
};
