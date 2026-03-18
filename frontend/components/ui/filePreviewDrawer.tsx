"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import dynamic from 'next/dynamic';
import { Drawer, Spin, Button, Table } from 'antd';
import { Download, X, ZoomIn, ZoomOut, RotateCw } from 'lucide-react';
import Papa from 'papaparse';
import { FilePreviewProps } from '@/types/chat';
import { storageService } from '@/services/storageService';
import { MarkdownRenderer, extractMarkdownHeadings, type MarkdownHeading } from '@/components/ui/markdownRenderer';
import log from '@/lib/logger';

const PdfViewer = dynamic(() => import('@/components/ui/PdfViewer').then(mod => ({ default: mod.PdfViewer })), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full">
      <Spin size="large" />
    </div>
  ),
});

const CHUNK_SIZE = 128 * 1024;

const TXT_LINE_HEIGHT = 24;

const TXT_VIRTUAL_OVERSCAN = 10;

const CSV_ROW_HEIGHT = 40;

function normalizeCharsetLabel(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'gbk' || normalized === 'gb2312' || normalized === 'cp936') {
    return 'gb18030';
  }
  return normalized;
}

function extractCharsetFromContentType(contentType: string | null): string | null {
  if (!contentType) return null;
  const match = contentType.match(/charset\s*=\s*([^;\s]+)/i);
  if (!match?.[1]) return null;
  return normalizeCharsetLabel(match[1].replace(/^"|"$/g, ''));
}

function parseCsvLine(line: string): string[] {
  const parsed = Papa.parse<string[]>(line, {
    header: false,
    skipEmptyLines: false,
    dynamicTyping: false,
    delimiter: ',',
    quoteChar: '"',
    escapeChar: '"',
  });

  const row = parsed.data[0];
  if (Array.isArray(row)) {
    return row.map((cell) => (typeof cell === 'string' ? cell.trim() : String(cell ?? '').trim()));
  }

  return line.split(',').map((cell) => cell.trim());
}

type DetectedFileType = 'pdf' | 'image' | 'markdown' | 'csv' | 'text' | 'unknown';

export function FilePreviewDrawer({
  open,
  objectName,
  fileName,
  fileType: providedFileType,
  fileSize,
  onClose,
}: FilePreviewProps) {
  const { t } = useTranslation('common');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string>('');
  const [previewUrl, setPreviewUrl] = useState<string>('');
  const [loadingMore, setLoadingMore] = useState(false);
  const [showMarkdownToc, setShowMarkdownToc] = useState(false);

  const [txtLines, setTxtLines] = useState<string[]>([]);
  const [txtScrollTop, setTxtScrollTop] = useState(0);
  const txtContainerRef = useRef<HTMLDivElement | null>(null);
  const txtContainerHeightRef = useRef(600);
  const txtScrollRafRef = useRef<number | null>(null);

  const [csvRows, setCsvRows] = useState<string[][]>([]);
  const [csvTableHeight, setCsvTableHeight] = useState(400);
  const csvWrapperRef = useRef<HTMLDivElement | null>(null);
  const csvResizeObserverRef = useRef<ResizeObserver | null>(null);

  const [imageScale, setImageScale] = useState(1);
  const [imageRotation, setImageRotation] = useState(0);
  const [imageLoadError, setImageLoadError] = useState(false);

  const [serverTooLarge, setServerTooLarge] = useState(false);

  const byteOffsetRef = useRef(0);
  const totalBytesRef = useRef<number | null>(null);
  const remainderRef = useRef('');
  const isFetchingRef = useRef(false);
  const previewUrlRef = useRef('');
  const textDecoderRef = useRef<TextDecoder | null>(null);
  const decoderEncodingRef = useRef<string | null>(null);
  const decoderHasExplicitCharsetRef = useRef(false);
  const decoderAllowGbFallbackRef = useRef(false);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const markdownContainerRef = useRef<HTMLDivElement | null>(null);
  const textFetchSessionRef = useRef(0);

  const resetTextPreviewState = useCallback(() => {
    setTextContent('');
    setTxtLines([]);
    setTxtScrollTop(0);
    setCsvRows([]);
    setLoadingMore(false);

    byteOffsetRef.current = 0;
    totalBytesRef.current = null;
    remainderRef.current = '';
    isFetchingRef.current = false;
    textDecoderRef.current = null;
    decoderEncodingRef.current = null;
    decoderHasExplicitCharsetRef.current = false;
    decoderAllowGbFallbackRef.current = false;

    observerRef.current?.disconnect();
    observerRef.current = null;
  }, []);

  const getDetectedFileType = useCallback((): DetectedFileType => {
    const mime = providedFileType?.toLowerCase() || '';

    if (mime === 'application/pdf') return 'pdf';
    
    if (mime === 'application/msword' || 
        mime === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
        mime === 'application/vnd.ms-excel' || 
        mime === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' ||
        mime === 'application/vnd.ms-powerpoint' || 
        mime === 'application/vnd.openxmlformats-officedocument.presentationml.presentation') {
      return 'pdf';
    }
    
    if (mime.startsWith('image/')) return 'image';
    
    if (mime === 'text/markdown') return 'markdown';
    
    if (mime === 'text/csv') return 'csv';
    
    if (mime === 'text/plain') return 'text';

    const extension = fileName.split('.').pop()?.toLowerCase() || '';
    
    if (extension === 'pdf') return 'pdf';
    if (['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].includes(extension)) return 'pdf';
    if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(extension)) return 'image';
    if (['md', 'markdown'].includes(extension)) return 'markdown';
    if (extension === 'csv') return 'csv';
    if (['txt', 'log', 'json', 'xml', 'yaml', 'yml'].includes(extension)) return 'text';

    return 'unknown';
  }, [providedFileType, fileName]);

  const detectedFileType = getDetectedFileType();

  const markdownHeadings = useMemo<MarkdownHeading[]>(() => {
    if (detectedFileType !== 'markdown' || !textContent) {
      return [];
    }
    return extractMarkdownHeadings(textContent);
  }, [detectedFileType, textContent]);
  
  const isTooLargeToPreview = !!(fileSize && fileSize > 100 * 1024 * 1024);

  const fetchTextChunk = useCallback(async (url: string, isFirst = false, sessionId?: number): Promise<void> => {
    const activeSessionId = sessionId ?? textFetchSessionRef.current;
    if (isFetchingRef.current) return;
    if (totalBytesRef.current !== null && byteOffsetRef.current >= totalBytesRef.current) return;

    isFetchingRef.current = true;
    if (!isFirst) setLoadingMore(true);

    try {
      const start = byteOffsetRef.current;
      const end   = start + CHUNK_SIZE - 1;
      const resp = await fetch(url, {
        headers: { Range: `bytes=${start}-${end}` },
        cache: 'no-store',
      });
      if (activeSessionId !== textFetchSessionRef.current) return;
      if (resp.status === 413) {
        setServerTooLarge(true);
        if (isFirst) setLoading(false);
        else setLoadingMore(false);
        isFetchingRef.current = false;
        return;
      }
      if (resp.status === 416) {
        observerRef.current?.disconnect();
        if (isFirst) setLoading(false);
        else setLoadingMore(false);
        isFetchingRef.current = false;
        return;
      }
      if (!resp.ok && resp.status !== 206) throw new Error(`HTTP ${resp.status}`);

      const contentRange = resp.headers.get('Content-Range');
      let hasMore = false;
      const buf = await resp.arrayBuffer();
      if (activeSessionId !== textFetchSessionRef.current) return;
      if (contentRange) {
        const m = contentRange.match(/bytes (\d+)-(\d+)\/(\d+)/);
        if (m) {
          const fetchedEnd = +m[2];
          const total      = +m[3];
          byteOffsetRef.current = fetchedEnd + 1;
          totalBytesRef.current = total;
          hasMore = fetchedEnd + 1 < total;
        }
      } else {
        byteOffsetRef.current += buf.byteLength;
        hasMore = false;
      }

      if (!textDecoderRef.current) {
        const headerCharset = extractCharsetFromContentType(resp.headers.get('Content-Type'));
        if (headerCharset) {
          const normalized = normalizeCharsetLabel(headerCharset);
          const isUtf8 = normalized === 'utf-8' || normalized === 'utf8';

          textDecoderRef.current = isUtf8
            ? new TextDecoder('utf-8', { fatal: true })
            : new TextDecoder(normalized);
          decoderEncodingRef.current = isUtf8 ? 'utf-8' : normalized;
          decoderHasExplicitCharsetRef.current = true;
          decoderAllowGbFallbackRef.current = isUtf8;
        } else {
          // Start with strict UTF-8; if invalid bytes appear in later chunks, fallback to GB18030.
          textDecoderRef.current = new TextDecoder('utf-8', { fatal: true });
          decoderEncodingRef.current = 'utf-8';
          decoderHasExplicitCharsetRef.current = false;
          decoderAllowGbFallbackRef.current = true;
        }
      }

      let raw = '';
      try {
        raw = textDecoderRef.current.decode(buf, { stream: hasMore });
        if (!hasMore) {
          // Flush pending bytes in decoder state for the final chunk.
          raw += textDecoderRef.current.decode();
        }
      } catch (decodeErr) {
        const canFallbackToGb18030 =
          decoderAllowGbFallbackRef.current &&
          decoderEncodingRef.current === 'utf-8';

        if (!canFallbackToGb18030) {
          throw decodeErr;
        }

        log.warn('UTF-8 decode failed for preview stream, fallback to GB18030:', decodeErr);
        textDecoderRef.current = new TextDecoder('gb18030');
        decoderEncodingRef.current = 'gb18030';
        decoderAllowGbFallbackRef.current = false;

        raw = textDecoderRef.current.decode(buf, { stream: hasMore });
        if (!hasMore) {
          raw += textDecoderRef.current.decode();
        }
      }

      // Keep incomplete trailing line for next chunk to avoid broken rows.
      let safeText = remainderRef.current + raw;
      if (activeSessionId !== textFetchSessionRef.current) return;
      if (hasMore && detectedFileType !== 'markdown') {
        const lastNl = safeText.lastIndexOf('\n');
        if (lastNl !== -1) {
          remainderRef.current = safeText.slice(lastNl + 1);
          safeText = safeText.slice(0, lastNl + 1);
        } else {
          remainderRef.current = safeText;
          safeText = '';
        }
      } else {
        remainderRef.current = '';
      }

      if (detectedFileType === 'text') {
        if (safeText) {
          const newLines = safeText.split('\n');
          if (newLines[newLines.length - 1] === '') newLines.pop();
          setTxtLines(prev => [...prev, ...newLines]);
        }
      } else if (detectedFileType === 'csv') {
        if (safeText) {
          const newLines = safeText.split('\n').filter(l => l.trim().length > 0);
          setCsvRows(prev => [...prev, ...newLines.map(parseCsvLine)]);
        }
      } else {
        if (safeText) setTextContent(prev => prev + safeText);
      }
      if (!hasMore) observerRef.current?.disconnect();
    } finally {
      if (activeSessionId !== textFetchSessionRef.current) {
        return;
      }
      isFetchingRef.current = false;
      if (isFirst) setLoading(false);
      else setLoadingMore(false);
    }
  }, [detectedFileType]);

  const setupSentinelObserver = useCallback((node: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node) return;
    const observer = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting) {
        if (totalBytesRef.current === null || byteOffsetRef.current < totalBytesRef.current) {
          fetchTextChunk(previewUrlRef.current).catch(err =>
            log.error('Failed to fetch next text chunk:', err)
          );
        }
      }
    }, { threshold: 0.1 });
    observer.observe(node);
    observerRef.current = observer;
  }, [fetchTextChunk]);

  useEffect(() => {
    if (!open || !objectName) {
      return;
    }

    const loadPreview = async () => {
      setLoading(true);
      setError(null);

      try {
        const url = storageService.getPreviewUrl(objectName, fileName);
        setPreviewUrl(url);
        previewUrlRef.current = url;

        if (['markdown', 'csv', 'text'].includes(detectedFileType)) {
          textFetchSessionRef.current += 1;
          const sessionId = textFetchSessionRef.current;
          resetTextPreviewState();
          await fetchTextChunk(url, true, sessionId);
        } else {
          setLoading(false);
        }
      } catch (err) {
        log.error('Failed to load preview:', err);
        setError(err instanceof Error ? err.message : t('filePreview.previewFailed'));
        setLoading(false);
      }
    };

    loadPreview();
  }, [open, objectName, fileName, detectedFileType, t, fetchTextChunk, resetTextPreviewState]);

  useEffect(() => {
    if (!open) {
      if (txtScrollRafRef.current !== null) {
        cancelAnimationFrame(txtScrollRafRef.current);
        txtScrollRafRef.current = null;
      }
      setServerTooLarge(false);
      setImageScale(1);
      setImageRotation(0);
      setTextContent('');
      setTxtLines([]);
      setTxtScrollTop(0);
      setCsvRows([]);
      setCsvTableHeight(400);
      setPreviewUrl('');
      setError(null);
      setImageLoadError(false);
      setLoadingMore(false);
      setShowMarkdownToc(false);
      textFetchSessionRef.current += 1;
      byteOffsetRef.current = 0;
      totalBytesRef.current = null;
      remainderRef.current = '';
      isFetchingRef.current = false;
      previewUrlRef.current = '';
      textDecoderRef.current = null;
      decoderEncodingRef.current = null;
      decoderHasExplicitCharsetRef.current = false;
      decoderAllowGbFallbackRef.current = false;
      observerRef.current?.disconnect();
      observerRef.current = null;
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (detectedFileType === 'text' && !loading && txtContainerRef.current) {
      txtContainerHeightRef.current = txtContainerRef.current.clientHeight;
    }
  }, [detectedFileType, loading]);

  const handleDownload = async () => {
    try {
      await storageService.downloadFile(objectName, fileName);
    } catch (err) {
      log.error('Failed to download file:', err);
    }
  };

  const handleMarkdownHeadingClick = useCallback((headingId: string) => {
    const container = markdownContainerRef.current;
    const target = container?.querySelector<HTMLElement>(`#${CSS.escape(headingId)}`) ?? null;

    if (!container || !target) {
      return;
    }

    const containerRect = container.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const nextScrollTop = container.scrollTop + targetRect.top - containerRect.top;

    container.scrollTo({ top: Math.max(nextScrollTop, 0), behavior: 'smooth' });

    if (window.innerWidth < 768) {
      setShowMarkdownToc(false);
    }
  }, []);

  const formatFileSize = (size: number): string => {
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / (1024 * 1024)).toFixed(2)} MB`;
  };



  const renderLoading = () => (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
        <p className="text-sm text-gray-600">{t('filePreview.loading')}</p>
      </div>
    </div>
  );

  const renderCenteredErrorState = () => (
    <div className="flex items-center justify-center h-full">
      <div className="text-center max-w-md px-4">
        <p className="text-red-500 text-sm">{t('filePreview.previewFailed')}</p>
      </div>
    </div>
  );

  const renderError = () => renderCenteredErrorState();

  const renderPdfViewer = () => (
    <PdfViewer
      url={previewUrl}
      fileName={fileName}
    />
  );

  const renderImageViewer = () => (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-center p-2 border-b bg-gray-50">
        <div className="flex items-center gap-2">
          <Button
            type="text"
            onClick={() => setImageScale(prev => Math.max(prev - 0.25, 0.5))}
            title={t('filePreview.zoomOut')}
            disabled={imageScale <= 0.5}
            icon={<ZoomOut size={20} />}
          />
          <span className="text-sm font-medium min-w-[60px] text-center">
            {Math.round(imageScale * 100)}%
          </span>
          <Button
            type="text"
            onClick={() => setImageScale(prev => Math.min(prev + 0.25, 3))}
            title={t('filePreview.zoomIn')}
            disabled={imageScale >= 3}
            icon={<ZoomIn size={20} />}
          />
          <div className="w-px h-6 bg-gray-300 mx-2" />
          <Button
            type="text"
            onClick={() => setImageRotation(prev => (prev + 90) % 360)}
            title={t('filePreview.rotate')}
            icon={<RotateCw size={20} />}
          />
        </div>
      </div>
      <div className="flex-1 overflow-auto flex items-center justify-center p-4 bg-gray-100">
        {imageLoadError ? (
          renderCenteredErrorState()
        ) : (
          <img
            src={previewUrl}
            alt={fileName}
            style={{
              transform: `scale(${imageScale}) rotate(${imageRotation}deg)`,
              transition: 'transform 0.2s ease-in-out',
              maxWidth: '100%',
              maxHeight: '100%',
              objectFit: 'contain',
            }}
            className="select-none"
            draggable={false}
            onError={() => setImageLoadError(true)}
          />
        )}
      </div>
    </div>
  );

  const renderMarkdownViewer = () => (
    <div className="flex h-full min-h-0 bg-white">
      {markdownHeadings.length > 0 && (
        <aside className={`${showMarkdownToc ? 'flex' : 'hidden'} md:flex w-64 flex-shrink-0 flex-col border-r border-gray-200 bg-gray-50/70`}>
          <div className="flex items-center justify-between border-b border-gray-200 px-3 py-3">
            <span className="text-sm font-medium text-gray-700">
              {t('filePreview.markdownOutline', { defaultValue: '目录' })}
            </span>
            <Button
              type="text"
              size="small"
              className="md:!hidden"
              icon={<X size={14} />}
              onClick={() => setShowMarkdownToc(false)}
            />
          </div>
          <div className="flex-1 overflow-auto px-2 py-2">
            {markdownHeadings.map((heading) => (
              <Button
                key={heading.id}
                type="text"
                block
                className="!mb-1 !flex !h-auto !justify-start !px-2 !py-1.5 !text-left !text-gray-700 hover:!bg-gray-100"
                onClick={() => handleMarkdownHeadingClick(heading.id)}
              >
                <span
                  className="block whitespace-normal break-words text-sm"
                  style={{ paddingLeft: `${(heading.level - 1) * 12}px` }}
                >
                  {heading.text}
                </span>
              </Button>
            ))}
          </div>
        </aside>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        {markdownHeadings.length > 0 && (
          <div className="border-b border-gray-200 px-4 py-2 md:hidden">
            <Button type="default" size="small" onClick={() => setShowMarkdownToc(prev => !prev)}>
              {t('filePreview.markdownOutline', { defaultValue: '目录' })}
            </Button>
          </div>
        )}
        <div ref={markdownContainerRef} className="flex-1 overflow-auto px-6 pb-6 pt-0">
          <MarkdownRenderer 
            content={textContent}
            enableMultimodal={true}
            resolveS3Media={false}
          />
          <div ref={setupSentinelObserver} className="h-1" />
          {loadingMore && (
            <div className="flex justify-center py-4">
              <Spin size="small" />
            </div>
          )}
        </div>
      </div>
    </div>
  );

  const renderCsvViewer = () => {
    if (csvRows.length === 0) {
      return renderCenteredErrorState();
    }

    const headerRow = csvRows[0];
    const dataRows = csvRows.slice(1);

    const columns = headerRow.map((col, i) => ({
      key: String(i),
      dataIndex: String(i),
      title: col || `${t('filePreview.csv.column')} ${i + 1}`,
      ellipsis: true,
      width: 160,
    }));

    const dataSource = dataRows.map((row, rowIdx) => {
      const record: Record<string, string> = { _key: String(rowIdx) };
      headerRow.forEach((_, i) => { record[String(i)] = row[i] ?? ''; });
      return record;
    });

    return (
      <div
        ref={(el) => {
          csvWrapperRef.current = el;
          csvResizeObserverRef.current?.disconnect();
          if (el) {
            const ro = new ResizeObserver(() => {
              setCsvTableHeight(el.clientHeight - 39 - 32);
            });
            ro.observe(el);
            csvResizeObserverRef.current = ro;
            setCsvTableHeight(el.clientHeight - 39 - 32);
          }
        }}
        className="h-full flex flex-col overflow-hidden p-4"
      >
        <Table
          columns={columns}
          dataSource={dataSource}
          rowKey="_key"
          size="small"
          bordered
          virtual
          scroll={{ x: columns.length * 160, y: csvTableHeight }}
          pagination={false}
          onScroll={(e) => {
            const el = e.currentTarget as HTMLElement;
            if (
              el.scrollTop + el.clientHeight >= el.scrollHeight - CSV_ROW_HEIGHT * 30 &&
              !isFetchingRef.current &&
              (totalBytesRef.current === null || byteOffsetRef.current < totalBytesRef.current)
            ) {
              fetchTextChunk(previewUrlRef.current).catch(err =>
                log.error('Failed to fetch next CSV chunk:', err)
              );
            }
          }}
        />
        {loadingMore && (
          <div className="flex items-center justify-center py-3 border-t border-gray-100">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-500 mr-2" />
            <span className="text-sm text-gray-500">{t('filePreview.loading')}</span>
          </div>
        )}
        <div ref={setupSentinelObserver} className="h-1" />
      </div>
    );
  };

  const renderTextViewer = () => {
    const viewH = txtContainerHeightRef.current;
    const totalH = txtLines.length * TXT_LINE_HEIGHT;

    const firstVis = Math.floor(txtScrollTop / TXT_LINE_HEIGHT);
    const lastVis = Math.ceil((txtScrollTop + viewH) / TXT_LINE_HEIGHT);
    const renderFrom = Math.max(0, firstVis - TXT_VIRTUAL_OVERSCAN);
    const renderTo = Math.min(txtLines.length - 1, lastVis + TXT_VIRTUAL_OVERSCAN);

    const topPad = renderFrom * TXT_LINE_HEIGHT;
    const bottomPad = Math.max(0, (txtLines.length - 1 - renderTo) * TXT_LINE_HEIGHT);

    return (
      <div
        ref={txtContainerRef}
        className="h-full overflow-auto bg-white"
        onScroll={(e) => {
          const el = e.currentTarget;
          const scrollTop = el.scrollTop;
          txtContainerHeightRef.current = el.clientHeight;
          // Use RAF to avoid excessive re-renders while scrolling.
          if (txtScrollRafRef.current !== null) {
            cancelAnimationFrame(txtScrollRafRef.current);
          }
          txtScrollRafRef.current = requestAnimationFrame(() => {
            txtScrollRafRef.current = null;
            setTxtScrollTop(scrollTop);
          });
          if (
            scrollTop + el.clientHeight >= totalH - TXT_LINE_HEIGHT * 30 &&
            !isFetchingRef.current &&
            (totalBytesRef.current === null || byteOffsetRef.current < totalBytesRef.current)
          ) {
            fetchTextChunk(previewUrlRef.current).catch(err =>
              log.error('Failed to fetch next text chunk:', err)
            );
          }
        }}
      >
        <div className="font-mono text-sm px-6 py-4">
          <div>
            <div style={{ height: topPad }} />
            {txtLines.slice(renderFrom, renderTo + 1).map((line, i) => (
              <div
                key={renderFrom + i}
                style={{ height: TXT_LINE_HEIGHT, lineHeight: `${TXT_LINE_HEIGHT}px`, whiteSpace: 'pre' }}
              >
                {line || '\u00A0'}
              </div>
            ))}
            <div style={{ height: bottomPad }} />
          </div>
        </div>
        {loadingMore && (
          <div className="flex justify-center py-4">
            <Spin size="small" />
          </div>
        )}
      </div>
    );
  };

  const renderTooLarge = () => (
    <div className="flex items-center justify-center h-full">
      <p className="text-gray-500">{t('filePreview.tooLargeToPreview')}</p>
    </div>
  );

  const renderUnsupported = () => (
    <div className="flex items-center justify-center h-full">
      <p className="text-gray-500 text-sm">{t('filePreview.unsupportedSingleLine')}</p>
    </div>
  );

  const renderContent = () => {
    if (isTooLargeToPreview || serverTooLarge) return renderTooLarge();
    if (loading) return renderLoading();
    if (error) return renderError();

    switch (detectedFileType) {
      case 'pdf':
        return renderPdfViewer();
      case 'image':
        return renderImageViewer();
      case 'markdown':
        return renderMarkdownViewer();
      case 'csv':
        return renderCsvViewer();
      case 'text':
        return renderTextViewer();
      default:
        return renderUnsupported();
    }
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="right"
      size="65%"
      styles={{
        body: { padding: 0, height: '100%', display: 'flex', flexDirection: 'column' },
        header: { padding: '12px 16px', borderBottom: '1px solid #e5e7eb' },
      }}
      closeIcon={<X size={20} />}
      title={
        <div className="flex items-center min-w-0">
          <span className="truncate font-medium" title={fileName}>
            {fileName}
          </span>
          {fileSize !== undefined && fileSize > 0 && (
            <span className="text-sm text-gray-500 font-normal flex-shrink-0 ml-4">
              {formatFileSize(fileSize)}
            </span>
          )}
        </div>
      }
      extra={
        <Button
          type="primary"
          icon={<Download size={14} />}
          onClick={handleDownload}
        >
          {t('filePreview.download')}
        </Button>
      }
    >
      <div className="flex h-full flex-col">
        <div className="flex-1 overflow-hidden">
        {renderContent()}
        </div>
      </div>
    </Drawer>
  );
}
