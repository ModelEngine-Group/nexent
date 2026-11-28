// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { PDFDocumentProxy } from "pdfjs-dist";
import log from "@/lib/logger";

function Thumbnail({
  pdf,
  page,
  active,
  aspectRatio,
  onSelect,
}: {
  pdf: PDFDocumentProxy;
  page: number;
  active: boolean;
  aspectRatio?: number;
  onSelect: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const { t } = useTranslation("common");
  useEffect(() => {
    const button = buttonRef.current;
    const canvas = canvasRef.current;
    if (!button || !canvas) return;
    let cancelled = false;
    let task:
      | ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]>
      | undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        void pdf
          .getPage(page)
          .then(async (pdfPage) => {
            if (cancelled) return;
            const viewport = pdfPage.getViewport({
              scale: 352 / pdfPage.getViewport({ scale: 1 }).width,
            });
            canvas.width = viewport.width;
            canvas.height = viewport.height;
            const context = canvas.getContext("2d");
            if (!context) return;
            task = pdfPage.render({ canvasContext: context, viewport });
            await task.promise;
          })
          .catch((error) => {
            if (!cancelled)
              log.error("Failed to render PDF thumbnail", { page, error });
          });
      },
      { rootMargin: "160px" }
    );
    observer.observe(button);
    return () => {
      cancelled = true;
      observer.disconnect();
      task?.cancel();
    };
  }, [pdf, page]);
  return (
    <button
      ref={buttonRef}
      type="button"
      onClick={onSelect}
      aria-label={t("filePreview.pdf.thumbnailPage", { page })}
      aria-current={active ? "page" : undefined}
      className={`block w-full min-w-0 rounded px-1 py-2 text-center text-xs ${active ? "bg-blue-50 text-blue-700" : "text-gray-600 hover:bg-gray-200"}`}
    >
      <canvas
        ref={canvasRef}
        style={aspectRatio ? { aspectRatio } : undefined}
        className={`mx-auto mb-1 block h-auto w-full max-w-[176px] border bg-white shadow-sm ${active ? "border-blue-600" : "border-gray-300"}`}
      />
      {page}
    </button>
  );
}

export default function PdfThumbnailRail({
  pdf,
  currentPage,
  pageAspectRatio,
  onSelect,
}: {
  pdf: PDFDocumentProxy;
  currentPage: number;
  pageAspectRatio?: number;
  onSelect: (page: number) => void;
}) {
  const { t } = useTranslation("common");
  return (
    <nav
      aria-label={t("filePreview.pdf.thumbnails")}
      className="w-64 min-w-0 max-w-[40%] shrink-0 overflow-x-hidden overflow-y-auto border-r border-gray-200 bg-gray-100 p-2"
    >
      {Array.from({ length: pdf.numPages }, (_, index) => (
        <Thumbnail
          key={index + 1}
          pdf={pdf}
          page={index + 1}
          active={currentPage === index + 1}
          aspectRatio={pageAspectRatio}
          onSelect={() => onSelect(index + 1)}
        />
      ))}
    </nav>
  );
}
