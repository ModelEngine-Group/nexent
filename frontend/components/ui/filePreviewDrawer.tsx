"use client";

import { useState, useEffect, useCallback, useMemo, useRef, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from 'react';
import { useTranslation } from 'react-i18next';
import dynamic from 'next/dynamic';
import { Drawer, Spin, Button, Table } from 'antd';
import { Download, Maximize2, Minimize2, Minus, Plus, RotateCw, X } from 'lucide-react';
import { FilePreviewProps } from '@/types/chat';
import { DetectedFileType, ImageBaseMode } from '@/types/file';
import {
  CHUNK_SIZE,
  TEXT_RENDER_BLOCK_SIZE,
  CSV_ROW_HEIGHT,
  isValidContainerElement,
  updateChunkRangeState,
  ensurePreviewTextDecoder,
  decodePreviewChunk,
  decodeLocalTextFile,
  splitPreviewSafeText,
  shouldStopFetchingChunk,
  handlePreviewChunkBoundaryResponse,
  appendTextPreviewContent,
  parseCsvLine,
  detectCsvDelimiter,
  computeRotateFitScale,
  clamp,
  ignoreAbortError,
  getPageWrapperStyle,
} from '@/lib/filePreviewUtils';
import { storageService } from '@/services/storageService';
import { MarkdownRenderer, extractMarkdownHeadings, type MarkdownHeading } from '@/components/ui/markdownRenderer';
import { formatFileSize } from '@/lib/utils';
import log from '@/lib/logger';

const PdfViewer = dynamic(() => import('@/components/ui/PdfViewer').then(mod => ({ default: mod.PdfViewer })), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full">
      <Spin size="large" />
    </div>
  ),
});

export function FilePreviewDrawer(props: Readonly<FilePreviewProps>) {
  const { open, onClose } = props;
  const { t } = useTranslation('common');
  const isLocalSource = props.source === 'local';
  const localFile = isLocalSource ? props.file : null;
  const objectName = !isLocalSource ? props.objectName : '';
  const fileName = isLocalSource && localFile
    ? localFile.name
    : ('fileName' in props ? props.fileName : '');
  const providedFileType = isLocalSource && localFile
    ? localFile.type
    : ('fileType' in props ? props.fileType : undefined);
  const fileSize = isLocalSource && localFile
    ? localFile.size
    : ('fileSize' in props ? props.fileSize : undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string>('');
  const [previewUrl, setPreviewUrl] = useState<string>('');
  const [loadingMore, setLoadingMore] = useState(false);
  const [showMarkdownToc, setShowMarkdownToc] = useState(false);

  const [txtLines, setTxtLines] = useState<string[]>([]);

  const [csvRows, setCsvRows] = useState<string[][]>([]);
  const [csvTableHeight, setCsvTableHeight] = useState(400);
  const csvWrapperRef = useRef<HTMLDivElement | null>(null);
  const csvResizeObserverRef = useRef<ResizeObserver | null>(null);

  const [imageScale, setImageScale] = useState(1);
  const [imageRotation, setImageRotation] = useState(0);
  const [imageLoadError, setImageLoadError] = useState(false);
  const [imageNaturalSize, setImageNaturalSize] = useState({ width: 0, height: 0 });
  const [imageViewportSize, setImageViewportSize] = useState({ width: 0, height: 0 });
  const [imageBaseMode, setImageBaseMode] = useState<ImageBaseMode>('fit');
  const imageViewportResizeObserverRef = useRef<ResizeObserver | null>(null);
  const [imagePan, setImagePan] = useState({ x: 0, y: 0 });
  const [isImageDragging, setIsImageDragging] = useState(false);
  const imagePanRef = useRef({ x: 0, y: 0 });
  const imageScaleRef = useRef(1);
  const dragStateRef = useRef<{
    isDragging: boolean;
    pointerId: number | null;
    startX: number;
    startY: number;
    startPanX: number;
    startPanY: number;
  }>({
    isDragging: false,
    pointerId: null,
    startX: 0,
    startY: 0,
    startPanX: 0,
    startPanY: 0,
  });

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
  const csvDelimiterRef = useRef<string>(',');

  const resetTextPreviewState = useCallback(() => {
    setTextContent('');
    setTxtLines([]);
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
    csvDelimiterRef.current = ',';

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
      return isLocalSource ? 'office' : 'pdf';
    }
    
    if (mime.startsWith('image/')) return 'image';
    
    if (mime === 'text/markdown') return 'markdown';

    if (mime === 'text/csv') return 'csv';

    if (mime === 'text/html') return 'html';

    if (mime === 'text/plain') return 'text';

    const extension = fileName.split('.').pop()?.toLowerCase() || '';
    
    if (extension === 'pdf') return 'pdf';
    if (['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].includes(extension)) {
      return isLocalSource ? 'office' : 'pdf';
    }
    if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(extension)) return 'image';
    if (['md', 'markdown'].includes(extension)) return 'markdown';
    if (extension === 'csv') return 'csv';
    if (['html', 'htm'].includes(extension)) return 'html';
    if (['txt', 'log', 'json', 'xml', 'yaml', 'yml'].includes(extension)) return 'text';

    return 'unknown';
  }, [providedFileType, fileName, isLocalSource]);

  const detectedFileType = getDetectedFileType();

  const markdownHeadings = useMemo<MarkdownHeading[]>(() => {
    if (detectedFileType !== 'markdown' || !textContent) {
      return [];
    }
    return extractMarkdownHeadings(textContent);
  }, [detectedFileType, textContent]);

  const txtLineBlocks = useMemo(() => {
    const blocks: string[][] = [];
    for (let i = 0; i < txtLines.length; i += TEXT_RENDER_BLOCK_SIZE) {
      blocks.push(txtLines.slice(i, i + TEXT_RENDER_BLOCK_SIZE));
    }
    return blocks;
  }, [txtLines]);
  
  const isEmptyFile = fileSize === 0;
  const isTooLargeToPreview = !!(fileSize && fileSize > 100 * 1024 * 1024);

  const normalizedImageRotation = ((imageRotation % 360) + 360) % 360;
  const imageFitScale = useMemo(
    () => computeRotateFitScale(normalizedImageRotation, imageNaturalSize, imageViewportSize),
    [imageNaturalSize, imageViewportSize, normalizedImageRotation],
  );
  const imageBaseScale = imageBaseMode === 'fit' ? imageFitScale : 1;
  const effectiveImageScale = imageScale * imageBaseScale;
  const imageScaleMin = imageBaseScale > 0 ? 0.25 / imageBaseScale : 0.25;
  const imageScaleMax = imageBaseScale > 0 ? 6 / imageBaseScale : 6;

  const imageDisplaySize = useMemo(() => {
    const { width: naturalWidth, height: naturalHeight } = imageNaturalSize;
    if (naturalWidth <= 0 || naturalHeight <= 0) {
      return { width: 0, height: 0 };
    }
    const isQuarterTurn = normalizedImageRotation === 90 || normalizedImageRotation === 270;
    const displayWidth = (isQuarterTurn ? naturalHeight : naturalWidth) * effectiveImageScale;
    const displayHeight = (isQuarterTurn ? naturalWidth : naturalHeight) * effectiveImageScale;
    return { width: displayWidth, height: displayHeight };
  }, [imageNaturalSize, normalizedImageRotation, effectiveImageScale]);

  const clampImagePan = useCallback((pan: { x: number; y: number }) => {
    const { width: viewportWidth, height: viewportHeight } = imageViewportSize;
    const { width: displayWidth, height: displayHeight } = imageDisplaySize;
    if (viewportWidth <= 0 || viewportHeight <= 0 || displayWidth <= 0 || displayHeight <= 0) {
      return { x: 0, y: 0 };
    }

    const maxPanX = Math.max(0, (displayWidth - viewportWidth) / 2);
    const maxPanY = Math.max(0, (displayHeight - viewportHeight) / 2);
    return {
      x: clamp(pan.x, -maxPanX, maxPanX),
      y: clamp(pan.y, -maxPanY, maxPanY),
    };
  }, [imageDisplaySize, imageViewportSize]);

  useEffect(() => {
    imagePanRef.current = imagePan;
  }, [imagePan]);

  useEffect(() => {
    imageScaleRef.current = imageScale;
  }, [imageScale]);

  useEffect(() => {
    if (!open) return;
    if (imageNaturalSize.width === 0 || imageNaturalSize.height === 0) return;
    if (imageViewportSize.width === 0 || imageViewportSize.height === 0) return;
    const normalizedRotation = ((imageRotation % 360) + 360) % 360;
    const isQuarterTurn = normalizedRotation === 90 || normalizedRotation === 270;
    const rotatedWidth = isQuarterTurn ? imageNaturalSize.height : imageNaturalSize.width;
    const rotatedHeight = isQuarterTurn ? imageNaturalSize.width : imageNaturalSize.height;
    if (rotatedWidth > imageViewportSize.width || rotatedHeight > imageViewportSize.height) {
      setImageBaseMode('fit');
    } else {
      setImageBaseMode('actual');
    }
  }, [open, imageNaturalSize, imageViewportSize, imageRotation]);

  const handleImageViewportRef = useCallback((el: HTMLDivElement | null) => {
    imageViewportResizeObserverRef.current?.disconnect();
    imageViewportResizeObserverRef.current = null;

    if (!el) {
      setImageViewportSize({ width: 0, height: 0 });
      return;
    }

    const updateViewportSize = () => {
      setImageViewportSize({ width: el.clientWidth, height: el.clientHeight });
    };

    const observer = new ResizeObserver(updateViewportSize);
    observer.observe(el);
    imageViewportResizeObserverRef.current = observer;
    updateViewportSize();
  }, []);

  const handleImagePanReset = useCallback(() => {
    const nextPan = { x: 0, y: 0 };
    setImagePan(nextPan);
    imagePanRef.current = nextPan;
    setIsImageDragging(false);
  }, []);

  const applyImageScale = useCallback((nextScale: number, anchorX = 0, anchorY = 0) => {
    const currentScale = imageScaleRef.current;
    if (nextScale === currentScale) {
      return;
    }
    const scaleRatio = nextScale / currentScale;
    const currentPan = imagePanRef.current;
    const nextPan = clampImagePan({
      x: anchorX - scaleRatio * (anchorX - currentPan.x),
      y: anchorY - scaleRatio * (anchorY - currentPan.y),
    });
    imagePanRef.current = nextPan;
    setImagePan(nextPan);
    imageScaleRef.current = nextScale;
    setImageScale(nextScale);
  }, [clampImagePan]);

  const handleImageWheel = useCallback((event: ReactWheelEvent<HTMLDivElement>) => {
    if (imageLoadError) {
      return;
    }

    event.preventDefault();

    const currentScale = imageScaleRef.current;
    const zoomFactor = Math.exp(-event.deltaY * 0.0015);
    const nextScale = clamp(currentScale * zoomFactor, imageScaleMin, imageScaleMax);
    if (nextScale === currentScale) {
      return;
    }

    const rect = event.currentTarget.getBoundingClientRect();
    const cursorX = event.clientX - rect.left - rect.width / 2;
    const cursorY = event.clientY - rect.top - rect.height / 2;
    applyImageScale(nextScale, cursorX, cursorY);
  }, [applyImageScale, imageLoadError, imageScaleMin, imageScaleMax]);

  const handleImagePointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (imageLoadError || event.button !== 0) {
      return;
    }

    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsImageDragging(true);
    dragStateRef.current = {
      isDragging: true,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startPanX: imagePanRef.current.x,
      startPanY: imagePanRef.current.y,
    };
  }, [imageLoadError]);

  const handleImagePointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    if (!dragState.isDragging || dragState.pointerId !== event.pointerId) {
      return;
    }

    event.preventDefault();
    const nextPan = {
      x: dragState.startPanX + (event.clientX - dragState.startX),
      y: dragState.startPanY + (event.clientY - dragState.startY),
    };
    const clamped = clampImagePan(nextPan);
    imagePanRef.current = clamped;
    setImagePan(clamped);
  }, [clampImagePan]);

  const handleImagePointerEnd = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    if (dragState.pointerId !== event.pointerId) {
      return;
    }

    dragStateRef.current = {
      isDragging: false,
      pointerId: null,
      startX: 0,
      startY: 0,
      startPanX: 0,
      startPanY: 0,
    };
    setIsImageDragging(false);
  }, []);

  const handleImageDoubleClick = useCallback(() => {
    if (imageScale !== 1 || imageBaseMode !== 'fit') {
      setImageBaseMode('fit');
      setImageScale(1);
      imageScaleRef.current = 1;
    } else {
      setImageBaseMode('actual');
    }
  }, [imageBaseMode, imageScale]);

  const toggleImageBaseMode = useCallback(() => {
    if (imageBaseMode === 'fit') {
      setImageBaseMode('actual');
    } else {
      setImageBaseMode('fit');
    }
    setImageScale(1);
    imageScaleRef.current = 1;
    handleImagePanReset();
  }, [handleImagePanReset, imageBaseMode]);

  useEffect(() => {
    const clamped = clampImagePan(imagePanRef.current);
    imagePanRef.current = clamped;
    setImagePan(clamped);
  }, [clampImagePan, effectiveImageScale, normalizedImageRotation, imageViewportSize]);

  const fetchTextChunk = useCallback(async (url: string, isFirst = false, sessionId?: number): Promise<void> => {
    const activeSessionId = sessionId ?? textFetchSessionRef.current;
    if (!url) {
      if (isFirst) setLoading(false);
      else setLoadingMore(false);
      return;
    }
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
      if (shouldStopFetchingChunk(activeSessionId, textFetchSessionRef.current)) return;
      if (handlePreviewChunkBoundaryResponse(
        resp.status,
        isFirst,
        setServerTooLarge,
        setLoading,
        setLoadingMore,
        observerRef,
        isFetchingRef,
      )) {
        return;
      }
      if (!resp.ok && resp.status !== 206) throw new Error(`HTTP ${resp.status}`);

      const contentRange = resp.headers.get('Content-Range');
      const buf = await resp.arrayBuffer();
      if (shouldStopFetchingChunk(activeSessionId, textFetchSessionRef.current)) return;
      const hasMore = updateChunkRangeState(contentRange, buf.byteLength, byteOffsetRef, totalBytesRef);
      ensurePreviewTextDecoder(
        resp.headers.get('Content-Type'),
        textDecoderRef,
        decoderEncodingRef,
        decoderHasExplicitCharsetRef,
        decoderAllowGbFallbackRef,
      );
      const raw = decodePreviewChunk(
        buf,
        hasMore,
        textDecoderRef,
        decoderEncodingRef,
        decoderAllowGbFallbackRef,
      );
      const { remainder, safeText } = splitPreviewSafeText(
        raw,
        remainderRef.current,
        hasMore,
        detectedFileType,
      );
      if (shouldStopFetchingChunk(activeSessionId, textFetchSessionRef.current)) return;
      remainderRef.current = remainder;
      appendTextPreviewContent({
        detectedFileType,
        safeText,
        byteOffset: byteOffsetRef.current,
        currentChunkLength: buf.byteLength,
        csvDelimiterRef,
        setTxtLines,
        setCsvRows,
        setTextContent,
      });
      if (!hasMore) observerRef.current?.disconnect();
    } finally {
      if (shouldStopFetchingChunk(activeSessionId, textFetchSessionRef.current)) {
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
    if (!isValidContainerElement(node)) return;
    const observer = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting) {
        if (!isLocalSource && previewUrlRef.current && (totalBytesRef.current === null || byteOffsetRef.current < totalBytesRef.current)) {
          fetchTextChunk(previewUrlRef.current).catch(err =>
            log.error('Failed to fetch next text chunk:', err)
          );
        }
      }
    }, { threshold: 0.1 });
    observer.observe(node);
    observerRef.current = observer;
  }, [fetchTextChunk, isLocalSource]);

  useEffect(() => {
    if (!open || (!isLocalSource && !objectName)) {
      return;
    }

    const loadPreview = async () => {
      setLoading(true);
      setError(null);

      try {
        if (isEmptyFile) {
          setPreviewUrl('');
          setLoading(false);
          return;
        }

        let localPreviewUrl: string | null = null;

        if (isLocalSource && localFile) {
          resetTextPreviewState();
          const previousPreviewUrl = previewUrlRef.current;
          if (previousPreviewUrl.startsWith('blob:')) {
            URL.revokeObjectURL(previousPreviewUrl);
          }
          previewUrlRef.current = '';

          if (isTooLargeToPreview && ['text', 'markdown', 'csv', 'html'].includes(detectedFileType)) {
            setLoading(false);
            return;
          }
          
          if (detectedFileType === 'image' || detectedFileType === 'pdf') {
            localPreviewUrl = URL.createObjectURL(localFile);
            setPreviewUrl(localPreviewUrl);
            previewUrlRef.current = localPreviewUrl;
            setLoading(false);
            return;
          }

          if (detectedFileType === 'text') {
            const text = await decodeLocalTextFile(localFile);
            const newLines = text.split('\n');
            if (newLines.at(-1) === '') {
              newLines.pop();
            }
            setTxtLines(newLines);
            setLoading(false);
            return;
          }

          if (detectedFileType === 'markdown') {
            setTextContent(await decodeLocalTextFile(localFile));
            setLoading(false);
            return;
          }

          if (detectedFileType === 'html') {
            const html = await decodeLocalTextFile(localFile);
            setTextContent(html);
            setLoading(false);
            return;
          }

          if (detectedFileType === 'csv') {
            const text = await decodeLocalTextFile(localFile);
            const delimiter = detectCsvDelimiter(text);
            csvDelimiterRef.current = delimiter;
            const newLines = text.split('\n').filter(line => line.trim().length > 0);
            setCsvRows(newLines.map((line) => parseCsvLine(line, delimiter)));
            setLoading(false);
            return;
          }

          setLoading(false);
          return;
        }

        const url = storageService.getPreviewUrl(objectName, fileName);

          if (['markdown', 'csv', 'text', 'html'].includes(detectedFileType)) {
            textFetchSessionRef.current += 1;
            const sessionId = textFetchSessionRef.current;
            resetTextPreviewState();
            setPreviewUrl(url);
            previewUrlRef.current = url;
            await fetchTextChunk(url, true, sessionId);
            return;
          }

        setPreviewUrl(url);
        previewUrlRef.current = url;

        setLoading(false);
      } catch (err) {
        log.error('Failed to load preview:', err);
        setError(err instanceof Error ? err.message : t('filePreview.previewFailed'));
        setLoading(false);
      }
    };

    void loadPreview();
  }, [open, objectName, fileName, detectedFileType, t, fetchTextChunk, resetTextPreviewState, isEmptyFile, isLocalSource, localFile]);

  useEffect(() => {
    return () => {
      const currentPreviewUrl = previewUrlRef.current;
      if (currentPreviewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(currentPreviewUrl);
      }
    };
  }, []);

  useEffect(() => {
    if (!open) {
      const previousPreviewUrl = previewUrlRef.current;
      setServerTooLarge(false);
      setImageScale(1);
      setImageRotation(0);
      setImageNaturalSize({ width: 0, height: 0 });
      setImageViewportSize({ width: 0, height: 0 });
      setImageBaseMode('fit');
      handleImagePanReset();
      setTextContent('');
      setTxtLines([]);
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
      textDecoderRef.current = null;
      decoderEncodingRef.current = null;
      decoderHasExplicitCharsetRef.current = false;
      decoderAllowGbFallbackRef.current = false;
      observerRef.current?.disconnect();
      observerRef.current = null;
      imageViewportResizeObserverRef.current?.disconnect();
      imageViewportResizeObserverRef.current = null;
      if (previousPreviewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(previousPreviewUrl);
      }
      previewUrlRef.current = '';
    }
  }, [open]);

  useEffect(() => {
    return () => {
      imageViewportResizeObserverRef.current?.disconnect();
      imageViewportResizeObserverRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    globalThis.addEventListener('keydown', handleKeyDown);
    return () => globalThis.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  const handleDownload = async () => {
    try {
      if (isLocalSource && localFile) {
        const url = URL.createObjectURL(localFile);
        const link = document.createElement('a');
        link.href = url;
        link.download = fileName;
        link.click();
        URL.revokeObjectURL(url);
        return;
      }

      await storageService.downloadFile(objectName, fileName);
    } catch (err) {
      log.error('Failed to download file:', err);
    }
  };

  const fetchNextTextChunk = useCallback(() => {
    if (isLocalSource) {
      return;
    }

    if (!previewUrlRef.current) {
      return;
    }

    if (
      isFetchingRef.current ||
      (totalBytesRef.current !== null && byteOffsetRef.current >= totalBytesRef.current)
    ) {
      return;
    }

    fetchTextChunk(previewUrlRef.current).catch(err =>
      log.error('Failed to fetch next text chunk:', err)
    );
  }, [fetchTextChunk, isLocalSource]);

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

    if (globalThis.innerWidth < 768) {
      setShowMarkdownToc(false);
    }
  }, []);

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
    <div className="h-full relative bg-gray-100">
      <div
        ref={handleImageViewportRef}
        className="relative h-full overflow-hidden bg-gray-100 p-4 pb-20 select-none touch-none cursor-grab active:cursor-grabbing"
        onWheel={handleImageWheel}
        onPointerDown={handleImagePointerDown}
        onPointerMove={handleImagePointerMove}
        onPointerUp={handleImagePointerEnd}
        onPointerCancel={handleImagePointerEnd}
        onLostPointerCapture={handleImagePointerEnd}
        onDoubleClick={handleImageDoubleClick}
      >
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          {imageLoadError ? (
            renderCenteredErrorState()
          ) : (
            <div
              className="absolute inset-0 flex items-center justify-center"
              style={{
                perspective: '1000px',
              }}
            >
              <div
                style={{
                  transform: `translate(${imagePan.x}px, ${imagePan.y}px) scale(${effectiveImageScale}) rotate(${imageRotation}deg)`,
                  willChange: 'transform',
                  transition: isImageDragging ? 'none' : 'transform 0.2s ease-in-out',
                }}
              >
                <img
                  src={previewUrl}
                  alt={fileName}
                  className="block select-none max-w-none"
                  draggable={false}
                  onLoad={(e) => {
                    const img = e.currentTarget;
                    setImageNaturalSize({ width: img.naturalWidth, height: img.naturalHeight });
                  }}
                  onError={() => setImageLoadError(true)}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {!imageLoadError && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10">
          <div className="flex items-center gap-1 bg-white/70 backdrop-blur-sm border border-gray-200/60 rounded-full shadow-lg px-3 py-1">
            <button
              onClick={() => {
                const nextScale = clamp(imageScaleRef.current - 0.25, imageScaleMin, imageScaleMax);
                applyImageScale(nextScale, 0, 0);
              }}
              disabled={effectiveImageScale <= 0.25}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-30 text-gray-600"
              title={t('filePreview.zoomOut')}
            >
              <Minus size={16} />
            </button>

            <span className="px-1 text-sm text-gray-500 select-none min-w-[52px] text-center">
              {Math.round(effectiveImageScale * 100)}%
            </span>

            <button
              onClick={() => {
                const nextScale = clamp(imageScaleRef.current + 0.25, imageScaleMin, imageScaleMax);
                applyImageScale(nextScale, 0, 0);
              }}
              disabled={effectiveImageScale >= 6}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-30 text-gray-600"
              title={t('filePreview.zoomIn')}
            >
              <Plus size={16} />
            </button>

            <div className="w-px h-5 bg-gray-200 mx-1" />

            <button
              onClick={toggleImageBaseMode}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-600"
              title={
                imageBaseMode === 'fit'
                  ? t('filePreview.image.actualSize')
                  : t('filePreview.image.fitPage')
              }
            >
              {imageBaseMode === 'fit' ? <Maximize2 size={16} /> : <Minimize2 size={16} />}
            </button>

            <button
              onClick={() => {
                setImageRotation(prev => prev + 90);
                handleImagePanReset();
              }}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-600"
              title={t('filePreview.rotate')}
            >
              <RotateCw size={16} />
            </button>
          </div>
        </div>
      )}
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

  const renderHtmlViewer = () => {
    return (
      <div
        className="h-full w-full overflow-auto bg-white"
        onScroll={(e) => {
          const el = e.currentTarget;
          if (
            !isLocalSource &&
            el.scrollTop + el.clientHeight >= el.scrollHeight - el.clientHeight * 0.5 &&
            !isFetchingRef.current &&
            (totalBytesRef.current === null || byteOffsetRef.current < totalBytesRef.current)
          ) {
            fetchNextTextChunk();
          }
        }}
      >
        <div
          className="html-preview-content px-6 py-4"
          dangerouslySetInnerHTML={{ __html: textContent }}
        />
        {loadingMore && (
          <div className="flex justify-center py-4">
            <Spin size="small" />
          </div>
        )}
      </div>
    );
  };

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
              !isLocalSource &&
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
    return (
      <div
        className="h-full min-h-0 w-full overflow-y-auto overflow-x-hidden bg-white"
        onScroll={(e) => {
          const el = e.currentTarget;
          if (
            !isLocalSource &&
            el.scrollTop + el.clientHeight >= el.scrollHeight - el.clientHeight * 0.5 &&
            !isFetchingRef.current &&
            (totalBytesRef.current === null || byteOffsetRef.current < totalBytesRef.current)
          ) {
            fetchNextTextChunk();
          }
        }}
      >
        <div className="px-6 py-4 font-mono text-sm leading-6">
          {txtLineBlocks.map((block, index) => (
            <pre
              key={index}
              className="m-0 whitespace-pre-wrap break-words"
              style={{
                contentVisibility: 'auto',
                containIntrinsicSize: `${Math.max(block.length, 1) * 24}px`,
              }}
            >
              {block.join('\n') || '\u00A0'}
            </pre>
          ))}
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

  const renderEmptyFile = () => (
    <div className="flex items-center justify-center h-full">
      <p className="text-gray-500 text-sm">{t('filePreview.emptyFile')}</p>
    </div>
  );

  const renderUnsupported = () => (
    <div className="flex items-center justify-center h-full">
      <p className="text-gray-500 text-sm">{t('filePreview.unsupportedSingleLine')}</p>
    </div>
  );

  const renderUploadToPreview = () => (
    <div className="flex items-center justify-center h-full">
      <p className="text-gray-500 text-sm">{t('filePreview.uploadToPreview')}</p>
    </div>
  );

  const renderContent = () => {
    if (isTooLargeToPreview || serverTooLarge) return renderTooLarge();
    if (isEmptyFile) return renderEmptyFile();
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
      case 'html':
        return renderHtmlViewer();
      case 'office':
        return renderUploadToPreview();
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
        body: { padding: 0, height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' },
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
        <div className="flex-1 min-h-0 overflow-hidden">
        {renderContent()}
        </div>
      </div>
    </Drawer>
  );
}
