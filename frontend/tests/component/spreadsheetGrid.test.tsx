// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeAll, describe, expect, it } from "vitest";

import {
  buildSheetGrid,
  columnIndexToLetters,
  XLSX_MAX_ROWS_PER_SHEET,
} from "@/lib/spreadsheetGrid";

type ExcelModule = typeof import("exceljs");
let ExcelJS: ExcelModule;

beforeAll(async () => {
  const loaded = await import("exceljs");
  ExcelJS = (loaded.default ?? loaded) as ExcelModule;
});

/** Build one worksheet through a filler so each case states only its own data. */
const sheetFrom = (fill: (sheet: import("exceljs").Worksheet) => void) => {
  const workbook = new ExcelJS.Workbook();
  const worksheet = workbook.addWorksheet("Sheet1");
  fill(worksheet);
  return worksheet;
};

describe("buildSheetGrid", () => {
  it("keeps a row whose value sits far below the first row", () => {
    const worksheet = sheetFrom((sheet) => {
      sheet.getCell("A10").value = "tenth row";
    });

    const grid = buildSheetGrid(worksheet);

    // ExcelJS reports `actualRowCount === 1` for this sheet: sizing the grid
    // from it renders one row, drops the rest and claims nothing was truncated.
    expect(grid.rows).toHaveLength(10);
    expect(grid.rows[9][0]?.text).toBe("tenth row");
    expect(grid.truncated).toBe(false);
  });

  it("keeps the leading empty rows so row numbers stay addressable", () => {
    const worksheet = sheetFrom((sheet) => {
      sheet.getCell("A5").value = "fifth row";
    });

    const grid = buildSheetGrid(worksheet);

    expect(grid.rows).toHaveLength(5);
    expect(grid.rows[0][0]?.text).toBe("");
    expect(grid.rows[4][0]?.text).toBe("fifth row");
  });

  it("keeps an empty row between two data rows", () => {
    const worksheet = sheetFrom((sheet) => {
      sheet.getCell("A1").value = "first";
      sheet.getCell("A3").value = "third";
    });

    const grid = buildSheetGrid(worksheet);

    expect(grid.rows).toHaveLength(3);
    expect(grid.rows[0][0]?.text).toBe("first");
    expect(grid.rows[1][0]?.text).toBe("");
    expect(grid.rows[2][0]?.text).toBe("third");
  });

  it("truncates a sheet longer than the rendered window", () => {
    const worksheet = sheetFrom((sheet) => {
      sheet.getCell(`A${XLSX_MAX_ROWS_PER_SHEET + 1}`).value =
        "past the window";
    });

    const grid = buildSheetGrid(worksheet);

    expect(grid.rows).toHaveLength(XLSX_MAX_ROWS_PER_SHEET);
    expect(grid.truncated).toBe(true);
  });

  it("collapses a merged range into its anchor", () => {
    const worksheet = sheetFrom((sheet) => {
      sheet.getCell("A1").value = "merged title";
      sheet.mergeCells("A1:B2");
    });

    const grid = buildSheetGrid(worksheet);

    expect(grid.rows[0][0]).toMatchObject({
      text: "merged title",
      rowSpan: 2,
      colSpan: 2,
    });
    expect(grid.rows[0][1]).toBeNull();
    expect(grid.rows[1][0]).toBeNull();
  });

  it("returns no rows for an empty sheet", () => {
    const grid = buildSheetGrid(sheetFrom(() => {}));

    expect(grid.rows).toHaveLength(0);
    expect(grid.truncated).toBe(false);
  });
});

describe("columnIndexToLetters", () => {
  it("labels the columns the grid header shows", () => {
    expect(columnIndexToLetters(0)).toBe("A");
    expect(columnIndexToLetters(25)).toBe("Z");
    expect(columnIndexToLetters(26)).toBe("AA");
  });
});
