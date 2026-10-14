"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Spin } from "antd";
import type { Fill, Slide as PptxSlide, TableCell } from "pptxtojson";

import {
  fetchPreviewBlobWithMeta,
  ignoreAbortError,
  PreviewAccessError,
  type PreviewAccessReason,
} from "@/lib/filePreviewUtils";
import {
  officeHtmlToText,
  resolveStreamPreviewKind,
  sanitizeOfficeHtml,
  type StreamPreviewKind,
} from "@/lib/officePreview";
import log from "@/lib/logger";

const PdfViewer = dynamic(
  () =>
    import("@/components/common/PdfViewer").then((mod) => ({
      default: mod.PdfViewer,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-full">
        <Spin size="large" />
      </div>
    ),
  }
);

/** Rows/columns rendered per sheet before the preview is truncated. */
const XLSX_MAX_ROWS_PER_SHEET = 300;
const XLSX_MAX_COLUMNS_PER_SHEET = 40;

type PreviewStatus = "loading" | "ready" | "error";

interface SheetCell {
  text: string;
  colSpan: number;
  rowSpan: number;
}

interface SheetGrid {
  name: string;
  rows: (SheetCell | null)[][];
  truncated: boolean;
}

/** Parsed pptx backing the slide renderer. */
type PptxPresentation = {
  slides: PptxSlide[];
  size: { width: number; height: number };
};

/** Bytes plus the format the server actually served them in. */
interface StreamPayload {
  kind: StreamPreviewKind;
  blob: Blob;
  servedFileName: string;
}

export interface RawStreamPreviewViewerProps {
  /** URL that streams the document without a server-side format guarantee. */
  url: string;
  /** Uploaded file name, used until the response reports the served name. */
  fileName: string;
  /** Uploaded format hint (AIDP reports a bare extension, not a MIME type). */
  fileType?: string;
  /**
   * Called when the backend refuses the request (403) or the document is gone
   * (404). Returning `true` means the owner already handled it, typically by
   * closing the preview.
   */
  onAccessError?: (reason: PreviewAccessReason) => boolean;
}

const columnIndexFromLetters = (letters: string): number => {
  let index = 0;
  for (const letter of letters.toUpperCase()) {
    index = index * 26 + (letter.charCodeAt(0) - 64);
  }
  return index - 1;
};

/** Build the spreadsheet column label for a zero-based index: 0 -> A, 26 -> AA. */
const columnIndexToLetters = (index: number): string => {
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

/** Build a display grid for one worksheet, collapsing merged ranges. */
const buildSheetGrid = (worksheet: import("exceljs").Worksheet): SheetGrid => {
  const rowCount = Math.min(
    worksheet.actualRowCount || worksheet.rowCount || 0,
    XLSX_MAX_ROWS_PER_SHEET
  );
  const columnCount = Math.min(
    worksheet.columnCount || 0,
    XLSX_MAX_COLUMNS_PER_SHEET
  );

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

  return {
    name: worksheet.name,
    rows,
    truncated:
      (worksheet.actualRowCount || worksheet.rowCount || 0) > rowCount ||
      (worksheet.columnCount || 0) > columnCount,
  };
};

const fillStyle = (fill: Fill | undefined): React.CSSProperties | undefined => {
  if (!fill) {
    return undefined;
  }
  switch (fill.type) {
    case "color":
      return { backgroundColor: fill.value };
    case "pattern":
      return { backgroundColor: fill.value.backgroundColor };
    case "gradient":
      return {
        backgroundImage: `linear-gradient(135deg, ${fill.value.colors
          .map((stop) => stop.color)
          .join(", ")})`,
      };
    case "image":
      return fill.value.base64
        ? {
            backgroundImage: `url(${fill.value.base64})`,
            backgroundSize: "cover",
          }
        : undefined;
    default:
      return undefined;
  }
};

const elementPositionStyle = (
  element: PptxSlide["elements"][number],
  size: { width: number; height: number }
): React.CSSProperties => {
  const widthRatio = size.width > 0 ? 100 / size.width : 0;
  const heightRatio = size.height > 0 ? 100 / size.height : 0;
  const rotate = "rotate" in element ? element.rotate : 0;
  return {
    left: `${element.left * widthRatio}%`,
    top: `${element.top * heightRatio}%`,
    width: `${element.width * widthRatio}%`,
    height: `${element.height * heightRatio}%`,
    transform: rotate ? `rotate(${rotate}deg)` : undefined,
  };
};

const renderPptxElement = (
  element: PptxSlide["elements"][number],
  size: { width: number; height: number },
  key: string
): React.ReactNode => {
  switch (element.type) {
    case "text":
    case "shape": {
      const html = sanitizeOfficeHtml(element.content);
      if (!html) {
        return null;
      }
      return (
        <div
          key={key}
          className="absolute overflow-hidden text-[10px] leading-snug text-gray-900"
          style={elementPositionStyle(element, size)}
          // Sanitized above: only layout/style-only markup survives, so no
          // script or remote resource in the document can reach the DOM.
          dangerouslySetInnerHTML={{ __html: html }}
        />
      );
    }
    case "image":
      return element.base64 ? (
        <img
          key={key}
          alt=""
          className="absolute object-contain"
          style={elementPositionStyle(element, size)}
          src={element.base64}
        />
      ) : null;
    case "table":
      return (
        <table
          key={key}
          className="absolute border-collapse text-[9px]"
          style={elementPositionStyle(element, size)}
        >
          <tbody>
            {element.data.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell: TableCell, cellIndex) => (
                  <td
                    key={cellIndex}
                    rowSpan={cell.rowSpan}
                    colSpan={cell.colSpan}
                    className="border border-gray-300 px-1 py-0.5 align-top"
                    style={{
                      backgroundColor: cell.fillColor,
                      fontWeight: cell.fontBold ? 600 : undefined,
                    }}
                  >
                    {officeHtmlToText(cell.text)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    default:
      // Charts, media, diagrams and equations are not rendered by this viewer.
      return null;
  }
};

/**
 * Preview a document whose format is only known from the response.
 *
 * AIDP serves the original bytes for docx/xlsx/pptx/pdf/txt and a PDF
 * conversion for every other format, so the uploaded name and `file_type`
 * cannot select the renderer: the response has to arrive first, and the name in
 * its `X-File-Name` header decides. Each renderer is imported on demand so the
 * parsers stay out of the initial bundle.
 */
export function RawStreamPreviewViewer(
  props: Readonly<RawStreamPreviewViewerProps>
) {
  const { url, fileName, fileType, onAccessError } = props;
  const { t } = useTranslation("common");

  const [status, setStatus] = useState<PreviewStatus>("loading");
  const [payload, setPayload] = useState<StreamPayload | null>(null);
  const [mediaUrl, setMediaUrl] = useState("");
  const [textContent, setTextContent] = useState("");
  const [sheets, setSheets] = useState<SheetGrid[]>([]);
  const [activeSheetIndex, setActiveSheetIndex] = useState(0);
  const [presentation, setPresentation] = useState<PptxPresentation | null>(
    null
  );

  const docxBodyRef = useRef<HTMLDivElement | null>(null);
  const docxStyleRef = useRef<HTMLDivElement | null>(null);
  const mediaUrlRef = useRef("");
  const onAccessErrorRef = useRef(onAccessError);
  onAccessErrorRef.current = onAccessError;

  const releaseMediaUrl = () => {
    if (mediaUrlRef.current) {
      URL.revokeObjectURL(mediaUrlRef.current);
      mediaUrlRef.current = "";
    }
  };

  useEffect(() => releaseMediaUrl, []);

  // Step 1: fetch the bytes once (a second request could be answered with a
  // different conversion) and learn which format they are in.
  useEffect(() => {
    if (!url) {
      return;
    }

    let cancelled = false;
    const controller = new AbortController();
    const { signal } = controller;

    setStatus("loading");
    setPayload(null);
    setSheets([]);
    setActiveSheetIndex(0);
    setPresentation(null);
    setTextContent("");
    setMediaUrl("");
    releaseMediaUrl();

    const load = async () => {
      const {
        blob,
        fileName: servedFileName,
        mimeType,
      } = await fetchPreviewBlobWithMeta(url, signal);
      if (cancelled) {
        return;
      }

      // The served name wins over the uploaded one: AIDP reports the name it
      // actually used, which ends in `.pdf` whenever the upload was converted.
      const resolvedName = servedFileName ?? fileName;
      setPayload({
        kind: resolveStreamPreviewKind(
          resolvedName,
          servedFileName ? undefined : fileType,
          mimeType
        ),
        blob,
        servedFileName: resolvedName,
      });
    };

    load().catch((error: unknown) => {
      if (ignoreAbortError(error) || cancelled) {
        return;
      }
      if (
        error instanceof PreviewAccessError &&
        onAccessErrorRef.current?.(error.reason)
      ) {
        setStatus("error");
        return;
      }
      log.error("Failed to load document stream:", error);
      if (!cancelled) {
        setStatus("error");
      }
    });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [url, fileName, fileType]);

  // Step 2: render the bytes. This runs after the commit that mounted the
  // container for the resolved format, so the docx target already exists.
  useEffect(() => {
    if (!payload) {
      return;
    }

    let cancelled = false;
    setStatus("loading");

    const render = async () => {
      const { kind, blob, servedFileName } = payload;
      log.info(`Preview stream "${servedFileName}" resolved to ${kind}`);

      if (kind === "pdf" || kind === "image") {
        releaseMediaUrl();
        mediaUrlRef.current = URL.createObjectURL(blob);
        if (cancelled) {
          return;
        }
        setMediaUrl(mediaUrlRef.current);
      } else if (kind === "text") {
        const text = await blob.text();
        if (cancelled) {
          return;
        }
        setTextContent(text);
      } else if (kind === "docx") {
        const { renderAsync } = await import("docx-preview");
        const body = docxBodyRef.current;
        if (cancelled || !body) {
          return;
        }
        body.innerHTML = "";
        await renderAsync(
          await blob.arrayBuffer(),
          body,
          docxStyleRef.current ?? undefined,
          {
            inWrapper: false,
            breakPages: true,
            ignoreLastRenderedPageBreak: true,
            renderHeaders: true,
            renderFooters: true,
          }
        );
      } else if (kind === "xlsx") {
        const excelModule = await import("exceljs");
        const ExcelJS = (excelModule.default ??
          excelModule) as typeof import("exceljs");
        const workbook = new ExcelJS.Workbook();
        await workbook.xlsx.load(await blob.arrayBuffer());
        const grids: SheetGrid[] = [];
        workbook.eachSheet((worksheet) => {
          grids.push(buildSheetGrid(worksheet));
        });
        if (cancelled) {
          return;
        }
        setSheets(grids);
      } else if (kind === "pptx") {
        const { parse } = await import("pptxtojson");
        const parsed = await parse(await blob.arrayBuffer(), {
          imageMode: "base64",
        });
        if (cancelled) {
          return;
        }
        setPresentation({ slides: parsed.slides, size: parsed.size });
      }

      if (!cancelled) {
        setStatus("ready");
      }
    };

    render().catch((error: unknown) => {
      log.error("Failed to render document preview:", error);
      if (!cancelled) {
        setStatus("error");
      }
    });

    return () => {
      cancelled = true;
    };
  }, [payload]);

  const renderLoading = () => (
    <div className="flex h-full items-center justify-center">
      <Spin size="large" />
    </div>
  );

  const renderMessage = (message: string) => (
    <div className="flex h-full items-center justify-center px-4">
      <p className="text-sm text-gray-500">{message}</p>
    </div>
  );

  const renderDocx = () => (
    <div className="relative h-full">
      {/* The container stays mounted while the document loads: `renderAsync`
          writes into it as soon as the bytes arrive, so it cannot depend on the
          ready state. */}
      {status !== "ready" && (
        <div className="absolute inset-0 z-10 bg-white">
          {status === "loading"
            ? renderLoading()
            : renderMessage(t("filePreview.previewFailed"))}
        </div>
      )}
      <div className="h-full overflow-auto bg-gray-200 p-4">
        <div ref={docxStyleRef} />
        <div ref={docxBodyRef} className="mx-auto max-w-[900px]" />
      </div>
    </div>
  );

  const renderXlsx = () => {
    const sheet = sheets[Math.min(activeSheetIndex, sheets.length - 1)];
    if (!sheet) {
      return renderLoading();
    }
    const columnCount = sheet.rows[0]?.length ?? 0;

    return (
      <div className="flex h-full flex-col bg-white">
        {/* Excel-like sheet tab strip: the active tab sits on the sheet, which
            is what tells the reader which worksheet these cells belong to. */}
        {sheets.length > 1 && (
          <div className="flex flex-shrink-0 flex-wrap items-end gap-1 border-b border-gray-200 bg-gray-50 px-3 pt-1.5">
            {sheets.map((item, index) => (
              <button
                key={`${index}-${item.name}`}
                type="button"
                onClick={() => setActiveSheetIndex(index)}
                className={
                  index === activeSheetIndex
                    ? "-mb-px rounded-t border border-b-0 border-gray-200 bg-white px-3 py-1 text-xs font-medium text-blue-600"
                    : "rounded-t border border-transparent px-3 py-1 text-xs text-gray-600 hover:bg-gray-100"
                }
              >
                {item.name}
              </button>
            ))}
          </div>
        )}
        {sheet.truncated && (
          <p className="flex-shrink-0 px-3 pt-2 text-xs text-amber-600">
            {t("filePreview.office.sheetTruncated", {
              count: XLSX_MAX_ROWS_PER_SHEET,
            })}
          </p>
        )}
        <div className="min-h-0 flex-1 overflow-auto">
          {/* A spreadsheet is read as a grid: column letters and row numbers
              give every cell an address, and a sticky header keeps them visible
              while scrolling. */}
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th className="sticky left-0 top-0 z-20 w-12 border border-gray-200 bg-gray-50 px-2 py-1" />
                {Array.from({ length: columnCount }, (_, columnIndex) => (
                  <th
                    key={columnIndex}
                    className="sticky top-0 z-10 min-w-[72px] border border-gray-200 bg-gray-50 px-2 py-1 text-center font-normal text-gray-500"
                  >
                    {columnIndexToLetters(columnIndex)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sheet.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="hover:bg-amber-50/60">
                  <th className="sticky left-0 z-10 w-12 border border-gray-200 bg-gray-50 px-2 py-1 text-right font-normal text-gray-500">
                    {rowIndex + 1}
                  </th>
                  {row.map((cell, columnIndex) =>
                    cell === null ? null : (
                      <td
                        key={columnIndex}
                        rowSpan={cell.rowSpan}
                        colSpan={cell.colSpan}
                        className="max-w-[360px] whitespace-pre-wrap break-words border border-gray-200 px-2 py-1 align-top"
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
      </div>
    );
  };

  const renderPptx = () => {
    // A presentation without a slide size cannot be scaled, so the geometry
    // below would collapse every element onto the origin.
    if (
      !presentation ||
      presentation.size.width <= 0 ||
      presentation.size.height <= 0
    ) {
      return renderMessage(t("filePreview.previewFailed"));
    }
    return (
      <div className="h-full space-y-4 overflow-auto bg-gray-200 p-4">
        {presentation.slides.map((slide, slideIndex) => (
          <div key={slideIndex} className="mx-auto w-full max-w-[1440px]">
            <p className="pb-1 text-xs text-gray-500">
              {t("filePreview.office.slide", { index: slideIndex + 1 })}
            </p>
            <div
              className="relative w-full overflow-hidden border border-gray-300 shadow-sm"
              style={{
                aspectRatio: `${presentation.size.width} / ${presentation.size.height}`,
                ...fillStyle(slide.fill),
              }}
            >
              {slide.elements.map((element, elementIndex) =>
                renderPptxElement(
                  element,
                  presentation.size,
                  `${slideIndex}-${elementIndex}`
                )
              )}
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderPdf = () => {
    // The blob URL only exists once the render effect has run; mounting the
    // viewer with an empty URL would ask pdf.js to open nothing.
    if (!mediaUrl) {
      return renderLoading();
    }
    return (
      // A document page is narrower than the full-screen surface, so fitting the
      // width uses the viewport instead of leaving a small page in a sea of gray.
      <PdfViewer
        url={mediaUrl}
        fileName={payload?.servedFileName ?? fileName}
        initialScaleMode="fit-width"
      />
    );
  };

  const renderImage = () => {
    if (!mediaUrl) {
      return renderLoading();
    }
    return (
      <div className="flex h-full items-center justify-center bg-gray-100 p-4">
        <img
          src={mediaUrl}
          alt={payload?.servedFileName ?? fileName}
          className="max-h-full max-w-full object-contain"
        />
      </div>
    );
  };

  // Formats AIDP serves unconverted but that have no dedicated renderer are
  // shown as plain text, which is what their bytes contain.
  const renderText = () => (
    <div className="h-full overflow-auto bg-white px-6 py-5">
      <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-800">
        {textContent}
      </pre>
    </div>
  );

  if (status === "error") {
    return renderMessage(t("filePreview.previewFailed"));
  }
  if (!payload) {
    return renderLoading();
  }

  switch (payload.kind) {
    case "pdf":
      return renderPdf();
    case "image":
      return renderImage();
    case "text":
      return renderText();
    case "docx":
      return renderDocx();
    case "xlsx":
      return status === "ready" ? renderXlsx() : renderLoading();
    case "pptx":
      return status === "ready" ? renderPptx() : renderLoading();
    default:
      return renderMessage(t("filePreview.office.streamUnsupported"));
  }
}
