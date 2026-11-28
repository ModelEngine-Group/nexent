// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Document, Page, pdfjs } from 'react-pdf';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { X } from 'lucide-react';
import { OutlineItem, PdfViewerProps, ScaleMode, ViewportAnchor } from '@/types/file';
import { ignoreAbortError, getPageWrapperStyle } from '@/lib/filePreviewUtils';
import { PDF_DOCUMENT_OPTIONS } from '@/lib/pdfPreviewOptions.mjs';
import log from '@/lib/logger';
import PdfThumbnailRail from './PdfThumbnailRail';
import PreviewControls from './PreviewControls';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

const OVERSCAN = 3;
const CONTAINER_TOP_PADDING = 24;
const PAGE_MARGIN_BOTTOM = 16;

function binarySearchPageAtOffset(cumulativeHeights: number[], offset: number): number {
  let lo = 0, hi = cumulativeHeights.length - 2;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (cumulativeHeights[mid] <= offset) lo = mid;
    else hi = mid - 1;
  }
  return lo + 1;
}

type PdfOutlineNode = {
  title: string;
  dest: string | unknown[] | null;
  items?: PdfOutlineNode[];
};

function buildRawOutline(items: PdfOutlineNode[]): OutlineItem[] {
  return items.map(item => ({
    title: item.title,
    dest: typeof item.dest === 'string' ? item.dest : null,
    items: item.items ? buildRawOutline(item.items) : undefined,
  }));
}

async function resolveOutlinePageNumbers(
  pdf: PDFDocumentProxy,
  items: PdfOutlineNode[],
): Promise<OutlineItem[]> {
  const result: OutlineItem[] = [];
  for (const item of items) {
    const pageNumber = await resolveOutlineItemPageNumber(pdf, item);
    result.push({
      title: item.title,
      dest: typeof item.dest === 'string' ? item.dest : null,
      pageNumber,
      items: item.items ? await resolveOutlinePageNumbers(pdf, item.items) : undefined,
    });
  }
  return result;
}

async function resolveOutlineItemPageNumber(
  pdf: PDFDocumentProxy,
  item: PdfOutlineNode,
): Promise<number | undefined> {
  if (!item.dest) {
    return undefined;
  }

  try {
    const dest = typeof item.dest === 'string'
      ? await pdf.getDestination(item.dest)
      : item.dest;
    if (!Array.isArray(dest) || !dest[0]) {
      return undefined;
    }

    const pageIndex = await pdf.getPageIndex(
      dest[0] as Parameters<PDFDocumentProxy['getPageIndex']>[0],
    );
    return pageIndex + 1;
  } catch (err) {
    log.warn('Failed to get page number for outline item:', err);
    return undefined;
  }
}

function PdfPageSlot({
  pageNum,
  isRendered,
  hasMeasuredHeight,
  pageScale,
  placeholderHeight,
  placeholderWidth,
  loadingText,
  onMeasured,
  onRenderError,
}: {
  pageNum: number;
  isRendered: boolean;
  hasMeasuredHeight: boolean;
  pageScale: number;
  placeholderHeight: number;
  placeholderWidth: number;
  loadingText: string;
  onMeasured: (pageNum: number, height: number) => void;
  onRenderError: (error: Error) => void;
}) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const pageWrapperStyle = getPageWrapperStyle(
    isRendered,
    hasMeasuredHeight,
    placeholderHeight,
    placeholderWidth,
  );
  return (
    <div ref={wrapperRef} className="bg-white shadow-lg mb-4" style={pageWrapperStyle}>
      {isRendered && (
        <Page
          pageNumber={pageNum}
          scale={pageScale}
          renderTextLayer={true}
          renderAnnotationLayer={true}
          onRenderError={onRenderError}
          onRenderTextLayerError={onRenderError}
          onRenderSuccess={() => {
            const element = wrapperRef.current;
            if (element) onMeasured(pageNum, element.offsetHeight);
          }}
          loading={
            <div
              className="flex flex-col items-center justify-center gap-2 bg-gray-50"
              style={{ height: placeholderHeight, width: placeholderWidth }}
            >
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
              <span className="text-xs text-gray-400">{loadingText}</span>
            </div>
          }
        />
      )}
    </div>
  );
}

export function PdfViewer({
  url,
  initialScaleMode = 'fit-page',
  enableThumbnails = false,
}: Readonly<PdfViewerProps>) {
  const { t } = useTranslation('common');

  const [numPages, setNumPages] = useState<number>(0);
  const [pageNumber, setPageNumber] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const toolbarRef = useRef<HTMLDivElement | null>(null);

  const [pdfDocument, setPdfDocument] = useState<PDFDocumentProxy | null>(null);
  const [showThumbnails, setShowThumbnails] = useState(false);
  const [outline, setOutline] = useState<OutlineItem[] | null>(null);
  const [showOutline, setShowOutline] = useState<boolean>(false);
  
  const [scaleMode, setScaleMode] = useState<ScaleMode>(initialScaleMode);
  const [customScale, setCustomScale] = useState<number>(1);
  const [containerWidth, setContainerWidth] = useState<number>(0);
  const [containerHeight, setContainerHeight] = useState<number>(0);
  // Defaults to portrait A4; updated after first page loads.
  const [intrinsicWidth, setIntrinsicWidth] = useState<number>(612);
  const [intrinsicHeight, setIntrinsicHeight] = useState<number>(792);

  const [pageHeights, setPageHeights] = useState<Map<number, number>>(new Map());
  // Expand immediately, shrink with debounce to avoid TextLayer abort noise.
  const [renderStart, setRenderStart] = useState<number>(1);
  const [renderEnd, setRenderEnd] = useState<number>(5);
  const shrinkTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingViewportAnchorRef = useRef<ViewportAnchor | null>(null);

  const pageScale = useMemo(() => {
    if (scaleMode === 'custom') return customScale;
    if (scaleMode === 'actual-size') return 1;
    if (scaleMode === 'fit-width') {
      if (!containerWidth) return 1;
      return Math.max(containerWidth / intrinsicWidth, 0.5);
    }
    if (scaleMode === 'fit-page') {
      const scaleByWidth = containerWidth ? containerWidth / intrinsicWidth : 1;
      const scaleByHeight = containerHeight ? containerHeight / intrinsicHeight : 1;
      return Math.max(Math.min(scaleByWidth, scaleByHeight), 0.3);
    }
    return 1;
  }, [scaleMode, customScale, containerWidth, containerHeight, intrinsicWidth, intrinsicHeight]);

  const estimatedPageHeight = useMemo(() => Math.round(intrinsicHeight * pageScale), [intrinsicHeight, pageScale]);

  const cumulativeHeights = useMemo(() => {
    const result = [0];
    for (let i = 1; i <= numPages; i++) {
      const slotH = (pageHeights.get(i) ?? estimatedPageHeight) + PAGE_MARGIN_BOTTOM;
      result.push(result[i - 1] + slotH);
    }
    return result;
  }, [numPages, pageHeights, estimatedPageHeight]);

  const captureViewportCenterAnchor = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container || !numPages) {
      pendingViewportAnchorRef.current = null;
      return;
    }

    const viewportCenterOffset =
      Math.max(0, container.scrollTop - CONTAINER_TOP_PADDING) + container.clientHeight / 2;
    const currentPage = binarySearchPageAtOffset(cumulativeHeights, viewportCenterOffset);
    const pageContentHeight = pageHeights.get(currentPage) ?? estimatedPageHeight;
    const pageStartOffset = cumulativeHeights[currentPage - 1];
    const offsetInsidePage = Math.min(
      Math.max(viewportCenterOffset - pageStartOffset, 0),
      pageContentHeight,
    );

    pendingViewportAnchorRef.current = {
      page: currentPage,
      pageOffsetRatio: pageContentHeight > 0 ? offsetInsidePage / pageContentHeight : 0,
    };
  }, [cumulativeHeights, estimatedPageHeight, numPages, pageHeights]);

  const onDocumentLoadSuccess = useCallback(async (pdf: PDFDocumentProxy) => {
    setNumPages(pdf.numPages);
    setPdfDocument(pdf);
    setLoading(false);
    log.info(`PDF loaded successfully: ${pdf.numPages} pages`);

    try {
      const firstPage = await pdf.getPage(1);
      const viewport = firstPage.getViewport({ scale: 1 });
      setIntrinsicWidth(viewport.width);
      setIntrinsicHeight(viewport.height);
    } catch (err) {
      log.warn('Failed to read first page dimensions, using defaults:', err);
    }

    try {
      const pdfOutline = await pdf.getOutline();

      if (pdfOutline && pdfOutline.length > 0) {
        const rawOutline = buildRawOutline(pdfOutline);
        setOutline(rawOutline);
        if (globalThis.innerWidth >= 768) setShowOutline(true);

        resolveOutlinePageNumbers(pdf, pdfOutline).then(resolved => {
          setOutline(resolved);
        }).catch(err => {
          log.warn('Failed to resolve outline page numbers:', err);
        });
      }
    } catch (err) {
      log.warn('Failed to load PDF outline:', err);
    }
  }, []);

  const onDocumentLoadError = useCallback((err: Error) => {
    log.error('Failed to load PDF:', err);
    setError(t('filePreview.previewFailed'));
    setLoading(false);
  }, [t]);

  const handlePageRenderError = useCallback((err: Error) => {
    if (ignoreAbortError(err)) return;
    log.error('Failed to render PDF page layer:', err);
  }, []);

  const handlePageMeasured = useCallback((pageNum: number, height: number) => {
    setPageHeights(prev => {
      if (prev.get(pageNum) === height) return prev;
      const next = new Map(prev);
      next.set(pageNum, height);
      return next;
    });
  }, []);

  const goToPage = useCallback((page: number) => {
    if (page >= 1 && page <= numPages) {
      const container = scrollContainerRef.current;
      if (container) {
        container.scrollTop = CONTAINER_TOP_PADDING + cumulativeHeights[page - 1];
      }
      setPageNumber(page);
    }
  }, [numPages, cumulativeHeights]);

  // react-pdf keeps a stale onItemClick closure; use ref to always call latest goToPage.
  const goToPageRef = useRef(goToPage);
  useEffect(() => { goToPageRef.current = goToPage; }, [goToPage]);
  const onItemClickStable = useCallback(
    ({ pageNumber: page }: { pageNumber: number }) => { if (page) goToPageRef.current(page); },
    []
  );

  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container || !numPages) return;
    const effectiveTop = Math.max(0, container.scrollTop - CONTAINER_TOP_PADDING);
    const firstPage = binarySearchPageAtOffset(cumulativeHeights, effectiveTop);
    const lastPage  = binarySearchPageAtOffset(cumulativeHeights, effectiveTop + container.clientHeight);
    const newStart = Math.max(1, firstPage - OVERSCAN);
    const newEnd   = Math.min(numPages, lastPage + OVERSCAN);
    setPageNumber(firstPage);
    setRenderStart(prev => Math.min(prev, newStart));
    setRenderEnd(prev => Math.max(prev, newEnd));
    if (shrinkTimerRef.current) clearTimeout(shrinkTimerRef.current);
    shrinkTimerRef.current = setTimeout(() => {
      setRenderStart(newStart);
      setRenderEnd(newEnd);
    }, 600);
  }, [cumulativeHeights, numPages]);

  const handleScrollRef = useRef(handleScroll);
  useEffect(() => { handleScrollRef.current = handleScroll; }, [handleScroll]);

  const previousPage = useCallback(() => {
    goToPage(pageNumber - 1);
  }, [pageNumber, goToPage]);

  const nextPage = useCallback(() => {
    goToPage(pageNumber + 1);
  }, [pageNumber, goToPage]);

  const adjustCustomScale = useCallback((delta: number) => {
    captureViewportCenterAnchor();
    setCustomScale(prev => {
      const baseScale = scaleMode === 'custom' ? prev : pageScale;
      return Math.min(Math.max(baseScale + delta, 0.5), 3);
    });
    setScaleMode('custom');
  }, [captureViewportCenterAnchor, scaleMode, pageScale]);

  const zoomIn = useCallback(() => {
    adjustCustomScale(0.25);
  }, [adjustCustomScale]);

  const zoomOut = useCallback(() => {
    adjustCustomScale(-0.25);
  }, [adjustCustomScale]);

  const onOutlineItemClick = useCallback((item: OutlineItem) => {
    if (item.pageNumber) {
      goToPage(item.pageNumber);
    }
  }, [goToPage]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const updateSize = () => {
      setContainerWidth(container.clientWidth - 48);
      setContainerHeight(container.clientHeight - 48);
    };
    const observer = new ResizeObserver(updateSize);
    observer.observe(container);
    updateSize();
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  useEffect(() => {
    if (numPages > 0) handleScrollRef.current();
  }, [numPages]);

  // Keep the current viewport center stable after zoom changes.
  useEffect(() => {
    const anchor = pendingViewportAnchorRef.current;
    if (!anchor) {
      return;
    }
    if (shrinkTimerRef.current) clearTimeout(shrinkTimerRef.current);
    const container = scrollContainerRef.current;
    setPageHeights(new Map());
    requestAnimationFrame(() => {
      if (container) {
        const clampedPage = Math.min(Math.max(anchor.page, 1), Math.max(numPages, 1));
        const pageStartOffset = (clampedPage - 1) * (estimatedPageHeight + PAGE_MARGIN_BOTTOM);
        const targetCenterOffset = pageStartOffset + anchor.pageOffsetRatio * estimatedPageHeight;
        const nextScrollTop = CONTAINER_TOP_PADDING + targetCenterOffset - container.clientHeight / 2;
        container.scrollTop = Math.max(nextScrollTop, 0);
      }
      pendingViewportAnchorRef.current = null;
    });
  }, [estimatedPageHeight, numPages, pageScale]);

  const renderOutlineItem = (item: OutlineItem, level: number = 0) => (
    <div key={`${item.title}-${level}`}>
      <button
        onClick={() => onOutlineItemClick(item)}
        className="w-full text-left px-3 py-1.5 hover:bg-gray-100 rounded transition-colors text-sm"
        style={{ paddingLeft: `${level * 12 + 12}px` }}
      >
        <span className="text-gray-800 break-words whitespace-normal">
          {item.title}
        </span>
      </button>
      {item.items && item.items.length > 0 && (
        <div>
          {item.items.map(child => renderOutlineItem(child, level + 1))}
        </div>
      )}
    </div>
  );

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-red-500 text-center">
          <p className="text-sm">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full bg-gray-100">
      {enableThumbnails && showThumbnails && pdfDocument && (
        <PdfThumbnailRail
          pdf={pdfDocument}
          currentPage={pageNumber}
          pageAspectRatio={intrinsicWidth / intrinsicHeight}
          onSelect={goToPage}
        />
      )}
      {showOutline && outline && outline.length > 0 && (
        <div className="w-64 bg-white border-r border-gray-200 flex flex-col flex-shrink-0">
          <div className="flex items-center justify-between p-3 border-b border-gray-200">
            <h3 className="font-medium text-sm">{t('filePreview.pdf.outline')}</h3>
            <button
              onClick={() => setShowOutline(false)}
              className="p-1 hover:bg-gray-100 rounded transition-colors"
              title={t('filePreview.pdf.hideOutline')}
            >
              <X size={16} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {outline.map(item => renderOutlineItem(item))}
          </div>
        </div>
      )}

      <div className="flex-1 flex flex-col overflow-hidden relative">

        {loading && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-gray-50/90 backdrop-blur-sm">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
              <p className="text-sm text-gray-600">{t('filePreview.loadingDocument')}</p>
            </div>
          </div>
        )}

        <div
          ref={scrollContainerRef}
          className="flex-1 overflow-auto py-6 flex flex-col items-center"
        >
          <Document
            file={url}
            options={PDF_DOCUMENT_OPTIONS}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onDocumentLoadError}
            onItemClick={onItemClickStable}
            loading={null}
          >
            {numPages > 0 && Array.from({ length: numPages }, (_, i) => i + 1).map(pageNum => {
              const isRendered = pageNum >= renderStart && pageNum <= renderEnd;
              return (
                <PdfPageSlot
                  key={pageNum}
                  pageNum={pageNum}
                  isRendered={isRendered}
                  hasMeasuredHeight={pageHeights.has(pageNum)}
                  pageScale={pageScale}
                  placeholderHeight={pageHeights.get(pageNum) ?? estimatedPageHeight}
                  placeholderWidth={Math.round(intrinsicWidth * pageScale)}
                  loadingText={t('filePreview.loadingPage')}
                  onMeasured={handlePageMeasured}
                  onRenderError={handlePageRenderError}
                />
              );
            })}
          </Document>
        </div>

        <PreviewControls
          zoom={pageScale}
          onZoom={(next) => {
            captureViewportCenterAnchor();
            setCustomScale(next);
            setScaleMode('custom');
          }}
          page={pageNumber}
          pages={numPages}
          onPage={goToPage}
          pageInput={{ value: pageNumber, onChange: goToPage }}
          onToggleThumbnails={
            enableThumbnails
              ? () => {
                  setShowThumbnails((value) => !value);
                  setShowOutline(false);
                }
              : undefined
          }
          thumbnailsOpen={showThumbnails}
          onToggleOutline={
            outline && outline.length > 0
              ? () => {
                  setShowOutline((value) => !value);
                  setShowThumbnails(false);
                }
              : undefined
          }
          outlineOpen={showOutline}
          zoomStep={0.25}
          minZoom={0.3}
          maxZoom={3}
          showActualSize={false}
          fitToggle={{
            active: scaleMode === 'fit-page',
            label:
              scaleMode === 'fit-page'
                ? t('filePreview.pdf.fitWidth')
                : t('filePreview.pdf.fitPage'),
            onToggle: () => {
              captureViewportCenterAnchor();
              setScaleMode((prev) =>
                prev === 'fit-page' ? 'fit-width' : 'fit-page'
              );
            },
          }}
        />
      </div>
    </div>
  );
}
