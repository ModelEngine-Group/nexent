// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useEffect, useState } from "react";
import { Alert, Spin } from "antd";
import { useTranslation } from "react-i18next";
import type { SheetGrid } from "@/lib/spreadsheetGrid";
import { columnIndexToLetters } from "@/lib/spreadsheetGrid";
import log from "@/lib/logger";
import PreviewControls from "./PreviewControls";
import styles from "./DocumentPreview.module.css";

export default function LegacySpreadsheetPreview({
  loadOriginal,
}: {
  loadOriginal: () => Promise<Response>;
}) {
  const { t } = useTranslation();
  const [sheets, setSheets] = useState<SheetGrid[]>([]);
  const [active, setActive] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    void loadOriginal()
      .then(async (response) => {
        const bytes = await response.arrayBuffer();
        const XLSX = await import("xlsx");
        const workbook = XLSX.read(bytes, {
          type: "array",
          cellText: true,
          cellStyles: true,
          sheetRows: 301,
        });
        const grids = workbook.SheetNames.map((name) => {
          const source = workbook.Sheets[name];
          const bounds = XLSX.utils.decode_range(source["!ref"] ?? "A1");
          const rowCount = Math.min(bounds.e.r + 1, 300),
            columnCount = Math.min(bounds.e.c + 1, 40);
          const rows: SheetGrid["rows"] = Array.from(
            { length: rowCount },
            (_, row) =>
              Array.from({ length: columnCount }, (_, column) => {
                const cell =
                  source[XLSX.utils.encode_cell({ r: row, c: column })];
                const fill = (
                  cell?.s as { fgColor?: { rgb?: string } } | undefined
                )?.fgColor?.rgb;
                const rgb =
                  fill && /^[0-9a-f]{6}$/i.test(fill) ? fill : undefined;
                const dark = rgb
                  ? (parseInt(rgb.slice(0, 2), 16) * 299 +
                      parseInt(rgb.slice(2, 4), 16) * 587 +
                      parseInt(rgb.slice(4, 6), 16) * 114) /
                      1000 <
                    145
                  : false;
                return {
                  style: {
                    ...(rgb
                      ? {
                          backgroundColor: `#${rgb}`,
                          color: dark ? "#ffffff" : "#191919",
                        }
                      : {}),
                    ...(cell?.t === "n" ? { textAlign: "right" as const } : {}),
                  },
                  text: cell ? (cell.w ?? XLSX.utils.format_cell(cell)) : "",
                  rowSpan: 1,
                  colSpan: 1,
                };
              })
          );
          for (const merge of source["!merges"] ?? []) {
            if (merge.s.r >= rowCount || merge.s.c >= columnCount) continue;
            const anchor = rows[merge.s.r][merge.s.c];
            if (!anchor) continue;
            anchor.rowSpan = Math.min(merge.e.r + 1, rowCount) - merge.s.r;
            anchor.colSpan = Math.min(merge.e.c + 1, columnCount) - merge.s.c;
            for (
              let row = merge.s.r;
              row <= Math.min(merge.e.r, rowCount - 1);
              row++
            )
              for (
                let column = merge.s.c;
                column <= Math.min(merge.e.c, columnCount - 1);
                column++
              )
                if (row !== merge.s.r || column !== merge.s.c)
                  rows[row][column] = null;
          }
          return {
            name,
            rows,
            truncated: bounds.e.r >= 300 || bounds.e.c >= 40,
            columnWidths: Array.from({ length: columnCount }, (_, column) =>
              Math.max(
                80,
                source["!cols"]?.[column]?.wpx ??
                  (source["!cols"]?.[column]?.wch ?? 16) * 7 + 5
              )
            ),
          };
        });
        if (!cancelled) setSheets(grids);
      })
      .catch((error) => {
        if (!cancelled) {
          log.error("Failed to read legacy spreadsheet", error);
          setError(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [loadOriginal]);
  if (error)
    return (
      <div className="p-6">
        <Alert type="error" title={t("filePreview.previewFailed")} />
      </div>
    );
  const sheet = sheets[active];
  if (!sheet)
    return (
      <div className="flex h-full items-center justify-center">
        <Spin />
      </div>
    );
  const columns = sheet.rows[0]?.length ?? 0;
  return (
    <div className={styles.reader}>
      <div className={styles.sheetTabs} role="tablist">
        {sheets.map((sheet, index) => (
          <button
            key={index}
            role="tab"
            aria-selected={active === index}
            onClick={() => setActive(index)}
          >
            {sheet.name}
          </button>
        ))}
      </div>
      {sheet.truncated && (
        <div className={styles.toolbar}>
          {t("filePreview.reader.truncated")}
        </div>
      )}
      <div className={styles.sheetViewport}>
        <table className={styles.grid} style={{ fontSize: 14 * zoom }}>
          <colgroup>
            <col style={{ width: 42 }} />
            {Array.from({ length: columns }, (_, column) => (
              <col
                key={column}
                style={{ width: (sheet.columnWidths?.[column] ?? 120) * zoom }}
              />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th />
              {Array.from({ length: columns }, (_, column) => (
                <th key={column}>{columnIndexToLetters(column)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sheet.rows.map((row, index) => (
              <tr key={index}>
                <td>{index + 1}</td>
                {row.map(
                  (cell, column) =>
                    cell && (
                      <td
                        key={column}
                        style={cell.style}
                        rowSpan={cell.rowSpan}
                        colSpan={cell.colSpan}
                      >
                        {cell.text}
                      </td>
                    )
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <PreviewControls zoom={zoom} onZoom={setZoom} onFit={() => setZoom(1)} />
    </div>
  );
}
