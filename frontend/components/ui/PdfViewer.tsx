"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Document, Page, pdfjs } from 'react-pdf';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { InputNumber } from 'antd';
import { 
  ChevronLeft, 
  ChevronRight, 
  Plus,
  Minus,
  Minimize2,
  Maximize2,
  Menu,
  X 
} from 'lucide-react';
import log from '@/lib/logger';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface OutlineItem {
  title: string;
  dest: string | null;
  items?: OutlineItem[];
  pageNumber?: number;
}

interface PdfViewerProps {
  url: string;
  fileName: string;
}

type ScaleMode = 'fit-width' | 'fit-page' | 'actual-size' | 'custom';

const PDF_DOCUMENT_OPTIONS = { rangeChunkSize: 65536 };

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

function ignoreAbortError(error: unknown): boolean {
  const errorName = typeof error === 'object' && error !== null && 'name' in error
    ? String((error as { name?: unknown }).name)
    : '';
  const errorMessage = typeof error === 'object' && error !== null && 'message' in error
    ? String((error as { message?: unknown }).message)
    : '';

  return errorName === 'AbortException' || errorMessage.includes('TextLayer task cancelled');
}

export function PdfViewer({ url, fileName }: PdfViewerProps) {
  const { t } = useTranslation('common');

  const [numPages, setNumPages] = useState<number>(0);
  const [pageNumber, setPageNumber] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  
  const [outline, setOutline] = useState<OutlineItem[] | null>(null);
  const [showOutline, setShowOutline] = useState<boolean>(false);
  
  const [scaleMode, setScaleMode] = useState<ScaleMode>('fit-page');
  const [customScale, setCustomScale] = useState<number>(1.0);
  const [containerWidth, setContainerWidth] = useState<number>(0);
  const [containerHeight, setContainerHeight] = useState<number>(0);
  // Defaults to portrait A4; updated after first page loads.
  const [intrinsicWidth, setIntrinsicWidth] = useState<number>(612);
  const [intrinsicHeight, setIntrinsicHeight] = useState<number>(792);

  const [pageHeights, setPageHeights] = useState<Map<number, number>>(new Map());
  const [visibleStart, setVisibleStart] = useState<number>(1);
  const [visibleEnd, setVisibleEnd] = useState<number>(5);
  // Expand immediately, shrink with debounce to avoid TextLayer abort noise.
  const [renderStart, setRenderStart] = useState<number>(1);
  const [renderEnd, setRenderEnd] = useState<number>(5);
  const shrinkTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const pageScale = useMemo(() => {
    if (scaleMode === 'custom') return customScale;
    if (scaleMode === 'actual-size') return 1.0;
    if (scaleMode === 'fit-width') {
      if (!containerWidth) return 1.0;
      return Math.max(containerWidth / intrinsicWidth, 0.5);
    }
    if (scaleMode === 'fit-page') {
      const scaleByWidth = containerWidth ? containerWidth / intrinsicWidth : 1.0;
      const scaleByHeight = containerHeight ? containerHeight / intrinsicHeight : 1.0;
      return Math.max(Math.min(scaleByWidth, scaleByHeight), 0.3);
    }
    return 1.0;
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

  const onDocumentLoadSuccess = useCallback(async (pdf: PDFDocumentProxy) => {
    setNumPages(pdf.numPages);
    setLoading(false);
    log.info(`PDF loaded successfully: ${pdf.numPages} pages`);

    try {
      const firstPage = await pdf.getPage(1);
      const viewport = firstPage.getViewport({ scale: 1.0 });
      setIntrinsicWidth(viewport.width);
      setIntrinsicHeight(viewport.height);
    } catch (err) {
      log.warn('Failed to read first page dimensions, using defaults:', err);
    }

    try {
      const pdfOutline = await pdf.getOutline();

      if (pdfOutline && pdfOutline.length > 0) {
        const buildRawOutline = (items: any[]): OutlineItem[] =>
          items.map(item => ({
            title: item.title,
            dest: typeof item.dest === 'string' ? item.dest : null,
            items: item.items ? buildRawOutline(item.items) : undefined,
          }));

        const rawOutline = buildRawOutline(pdfOutline);
        setOutline(rawOutline);
        if (window.innerWidth >= 768) setShowOutline(true);

        const resolvePageNumbers = async (items: any[]): Promise<OutlineItem[]> => {
          const result: OutlineItem[] = [];
          for (const item of items) {
            let pageNumber: number | undefined;
            if (item.dest) {
              try {
                const dest = typeof item.dest === 'string'
                  ? await pdf.getDestination(item.dest)
                  : item.dest;
                if (dest && dest[0]) {
                  const pageIndex = await pdf.getPageIndex(dest[0]);
                  pageNumber = pageIndex + 1;
                }
              } catch (err) {
                log.warn('Failed to get page number for outline item:', err);
              }
            }
            result.push({
              title: item.title,
              dest: typeof item.dest === 'string' ? item.dest : null,
              pageNumber,
              items: item.items ? await resolvePageNumbers(item.items) : undefined,
            });
          }
          return result;
        };

        resolvePageNumbers(pdfOutline).then(resolved => {
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
    setVisibleStart(newStart);
    setVisibleEnd(newEnd);
    setPageNumber(firstPage);
    setRenderStart(prev => Math.min(prev, newStart));
    setRenderEnd(prev => Math.max(prev, newEnd));
    if (shrinkTimerRef.current) clearTimeout(shrinkTimerRef.current);
    shrinkTimerRef.current = setTimeout(() => {
      setRenderStart(newStart);
      setRenderEnd(newEnd);
    }, 600);
  }, [cumulativeHeights, numPages]);

  const previousPage = useCallback(() => {
    goToPage(pageNumber - 1);
  }, [pageNumber, goToPage]);

  const nextPage = useCallback(() => {
    goToPage(pageNumber + 1);
  }, [pageNumber, goToPage]);

  const adjustCustomScale = useCallback((delta: number) => {
    setCustomScale(prev => {
      const baseScale = scaleMode === 'custom' ? prev : pageScale;
      return Math.min(Math.max(baseScale + delta, 0.5), 3.0);
    });
    setScaleMode('custom');
  }, [scaleMode, pageScale]);

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
    const updateSize = () => {
      const container = scrollContainerRef.current;
      if (container) {
        setContainerWidth(container.clientWidth - 48);
        setContainerHeight(container.clientHeight - 48);
      }
    };

    const timer = setTimeout(updateSize, 50);
    window.addEventListener('resize', updateSize);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('resize', updateSize);
    };
  }, [showOutline]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  useEffect(() => {
    if (numPages > 0) handleScroll();
  // handleScroll is stable once numPages and cumulativeHeights are set
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numPages]);

  const [toolbarVisible, setToolbarVisible] = useState(true);
  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resetIdleTimer = useCallback(() => {
    setToolbarVisible(true);
    if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    idleTimerRef.current = setTimeout(() => setToolbarVisible(false), 3000);
  }, []);

  useEffect(() => {
    resetIdleTimer();
    return () => { if (idleTimerRef.current) clearTimeout(idleTimerRef.current); };
  }, [resetIdleTimer]);

  // Keep current page position stable after zoom changes.
  useEffect(() => {
    if (shrinkTimerRef.current) clearTimeout(shrinkTimerRef.current);
    const container = scrollContainerRef.current;
    const currentPage = pageNumber; // capture before async RAF
    setPageHeights(new Map());
    requestAnimationFrame(() => {
      if (container) {
        const estimate = Math.round(intrinsicHeight * pageScale) + PAGE_MARGIN_BOTTOM;
        container.scrollTop = CONTAINER_TOP_PADDING + (currentPage - 1) * estimate;
      }
    });
  // pageNumber intentionally omitted — we only want the page at the moment the scale changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageScale]);

  const renderOutlineItem = (item: OutlineItem, level: number = 0) => (
    <div key={`${item.title}-${level}`} className="outline-item">
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
        <div className="outline-children">
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
          id="pdf-page-container"
          className="flex-1 overflow-auto py-6 flex flex-col items-center"
          onMouseMove={resetIdleTimer}
          onPointerDown={resetIdleTimer}
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
              const placeholderH = pageHeights.get(pageNum) ?? estimatedPageHeight;
              const placeholderW = Math.round(intrinsicWidth * pageScale);
              return (
                <div
                  key={pageNum}
                  ref={el => { pageRefs.current[pageNum - 1] = el; }}
                  className="bg-white shadow-lg mb-4"
                  style={
                    isRendered
                      ? (pageHeights.has(pageNum) ? undefined : { minHeight: placeholderH, width: placeholderW })
                      : { height: placeholderH, width: placeholderW }
                  }
                >
                  {isRendered && (
                    <Page
                      pageNumber={pageNum}
                      scale={pageScale}
                      renderTextLayer={true}
                      renderAnnotationLayer={true}
                      onRenderError={handlePageRenderError}
                      onRenderTextLayerError={handlePageRenderError}
                      onRenderSuccess={() => {
                        const el = pageRefs.current[pageNum - 1];
                        if (el) {
                          const measured = el.offsetHeight;
                          setPageHeights(prev => {
                            if (prev.get(pageNum) === measured) return prev;
                            const next = new Map(prev);
                            next.set(pageNum, measured);
                            return next;
                          });
                        }
                      }}
                      loading={
                        <div
                          className="flex flex-col items-center justify-center gap-2 bg-gray-50"
                          style={{ height: placeholderH, width: placeholderW }}
                        >
                          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                          <span className="text-xs text-gray-400">{t('filePreview.loadingPage')}</span>
                        </div>
                      }
                    />
                  )}
                </div>
              );
            })}
          </Document>
        </div>

        <div
          className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10 transition-opacity duration-300"
          style={{ opacity: toolbarVisible ? 1 : 0.15 }}
          onMouseEnter={() => { if (idleTimerRef.current) clearTimeout(idleTimerRef.current); setToolbarVisible(true); }}
          onMouseLeave={resetIdleTimer}
        >
          <div className="flex items-center gap-1 bg-white/70 backdrop-blur-sm border border-gray-200/60 rounded-full shadow-lg px-3 py-1">
            {outline && outline.length > 0 && (
              <>
                <button
                  onClick={() => setShowOutline(v => !v)}
                  className={`p-1.5 rounded-lg transition-colors text-sm flex items-center gap-1 ${showOutline ? 'bg-blue-100 text-blue-600' : 'hover:bg-gray-100 text-gray-600'}`}
                  title={showOutline ? t('filePreview.pdf.hideOutline') : t('filePreview.pdf.showOutline')}
                >
                  <Menu size={16} />
                </button>
                <div className="w-px h-5 bg-gray-200 mx-1" />
              </>
            )}

            <button
              onClick={previousPage}
              disabled={pageNumber <= 1}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-30 text-gray-600"
              title={t('filePreview.pdf.previousPage')}
            >
              <ChevronLeft size={16} />
            </button>

            <div className="flex items-center gap-1.5 px-1">
              <InputNumber
                size="small"
                min={1}
                max={numPages}
                value={pageNumber}
                onChange={(value) => value && goToPage(value)}
                className="w-12"
                controls={false}
                title={t('filePreview.pdf.goToPage')}
              />
              <span className="text-sm text-gray-500 select-none">/ {numPages}</span>
            </div>

            <button
              onClick={nextPage}
              disabled={pageNumber >= numPages}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-30 text-gray-600"
              title={t('filePreview.pdf.nextPage')}
            >
              <ChevronRight size={16} />
            </button>

            <div className="w-px h-5 bg-gray-200 mx-1" />

            <button
              onClick={zoomOut}
              disabled={scaleMode === 'custom' && customScale <= 0.5}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-30 text-gray-600"
              title={t('filePreview.zoomOut')}
            >
              <Minus size={16} />
            </button>

            <button
              onClick={() => setScaleMode(prev => prev === 'fit-page' ? 'fit-width' : 'fit-page')}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-600"
              title={scaleMode === 'fit-page' ? t('filePreview.pdf.fitWidth') : t('filePreview.pdf.fitPage')}
            >
              {scaleMode === 'fit-page' ? <Maximize2 size={16} /> : <Minimize2 size={16} />}
            </button>

            <button
              onClick={zoomIn}
              disabled={scaleMode === 'custom' && customScale >= 3.0}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-30 text-gray-600"
              title={t('filePreview.zoomIn')}
            >
              <Plus size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
