"use client";

import { useState, useEffect, useCallback, useMemo, useRef, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from 'react';
import { useTranslation } from 'react-i18next';
import dynamic from 'next/dynamic';
import { Drawer, Spin, Button, Table } from 'antd';
import { Download, Maximize2, Minimize2, Minus, Plus, RotateCw, X } from 'lucide-react';
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

const CSV_ROW_HEIGHT = 40;
const TEXT_RENDER_BLOCK_SIZE = 200;
const CSV_DELIMITER_CANDIDATES = [',', ';', '\t', '|'] as const;
const CHARSET_PATTERN = /charset\s*=\s*([^;\s]+)/i;
const CONTENT_RANGE_PATTERN = /bytes (\d+)-(\d+)\/(\d+)/;
const INVALID_CONTAINER_TAGS = new Set(['head', 'style', 'script', 'link', 'meta']);

function isValidContainerElement(el: Element | null): el is HTMLDivElement {
  if (!(el instanceof HTMLDivElement)) {
    return false;
  }

  if (!el.isConnected) {
    return false;
  }

  const tagName = el.tagName.toLowerCase();
  return !INVALID_CONTAINER_TAGS.has(tagName);
}

function normalizeCharsetLabel(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'gbk' || normalized === 'gb2312' || normalized === 'cp936') {
    return 'gb18030';
  }
  return normalized;
}

function extractCharsetFromContentType(contentType: string | null): string | null {
  if (!contentType) return null;
  const match = CHARSET_PATTERN.exec(contentType);
  if (!match?.[1]) return null;
  return normalizeCharsetLabel(match[1].replaceAll(/^"|"$/g, ''));
}

function updateChunkRangeState(
  contentRange: string | null,
  byteLength: number,
  byteOffsetRef: React.MutableRefObject<number>,
  totalBytesRef: React.MutableRefObject<number | null>,
): boolean {
  if (!contentRange) {
    byteOffsetRef.current += byteLength;
    return false;
  }

  const match = CONTENT_RANGE_PATTERN.exec(contentRange);
  if (!match) {
    byteOffsetRef.current += byteLength;
    return false;
  }

  const fetchedEnd = Number(match[2]);
  const total = Number(match[3]);
  byteOffsetRef.current = fetchedEnd + 1;
  totalBytesRef.current = total;
  return fetchedEnd + 1 < total;
}

function ensurePreviewTextDecoder(
  contentType: string | null,
  textDecoderRef: React.MutableRefObject<TextDecoder | null>,
  decoderEncodingRef: React.MutableRefObject<string | null>,
  decoderHasExplicitCharsetRef: React.MutableRefObject<boolean>,
  decoderAllowGbFallbackRef: React.MutableRefObject<boolean>,
): void {
  if (textDecoderRef.current) {
    return;
  }

  const headerCharset = extractCharsetFromContentType(contentType);
  if (headerCharset) {
    const normalized = normalizeCharsetLabel(headerCharset);
    const isUtf8 = normalized === 'utf-8' || normalized === 'utf8';

    textDecoderRef.current = isUtf8
      ? new TextDecoder('utf-8', { fatal: true })
      : new TextDecoder(normalized);
    decoderEncodingRef.current = isUtf8 ? 'utf-8' : normalized;
    decoderHasExplicitCharsetRef.current = true;
    decoderAllowGbFallbackRef.current = isUtf8;
    return;
  }

  // Start with strict UTF-8; if invalid bytes appear in later chunks, fallback to GB18030.
  textDecoderRef.current = new TextDecoder('utf-8', { fatal: true });
  decoderEncodingRef.current = 'utf-8';
  decoderHasExplicitCharsetRef.current = false;
  decoderAllowGbFallbackRef.current = true;
}

function decodePreviewChunk(
  buf: ArrayBuffer,
  hasMore: boolean,
  textDecoderRef: React.MutableRefObject<TextDecoder | null>,
  decoderEncodingRef: React.MutableRefObject<string | null>,
  decoderAllowGbFallbackRef: React.MutableRefObject<boolean>,
): string {
  if (!textDecoderRef.current) {
    throw new Error('Text decoder is not initialized');
  }

  try {
    let raw = textDecoderRef.current.decode(buf, { stream: hasMore });
    if (!hasMore) {
      raw += textDecoderRef.current.decode();
    }
    return raw;
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

    let raw = textDecoderRef.current.decode(buf, { stream: hasMore });
    if (!hasMore) {
      raw += textDecoderRef.current.decode();
    }
    return raw;
  }
}

async function decodeLocalTextFile(file: File): Promise<string> {
  const buf = await file.arrayBuffer();

  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buf);
  } catch {
    return new TextDecoder('gb18030').decode(buf);
  }
}

function splitPreviewSafeText(
  raw: string,
  remainder: string,
  hasMore: boolean,
  detectedFileType: DetectedFileType,
): { remainder: string; safeText: string } {
  const mergedText = remainder + raw;
  const shouldKeepTrailingLine = hasMore && detectedFileType !== 'markdown';
  if (!shouldKeepTrailingLine) {
    return { remainder: '', safeText: mergedText };
  }

  const lastNl = mergedText.lastIndexOf('\n');
  if (lastNl === -1) {
    return { remainder: mergedText, safeText: '' };
  }

  return {
    remainder: mergedText.slice(lastNl + 1),
    safeText: mergedText.slice(0, lastNl + 1),
  };
}

function shouldStopFetchingChunk(
  activeSessionId: number,
  currentSessionId: number,
): boolean {
  return activeSessionId !== currentSessionId;
}

function handlePreviewChunkBoundaryResponse(
  status: number,
  isFirst: boolean,
  setServerTooLarge: React.Dispatch<React.SetStateAction<boolean>>,
  setLoading: React.Dispatch<React.SetStateAction<boolean>>,
  setLoadingMore: React.Dispatch<React.SetStateAction<boolean>>,
  observerRef: React.MutableRefObject<IntersectionObserver | null>,
  isFetchingRef: React.MutableRefObject<boolean>,
): boolean {
  if (status === 413) {
    setServerTooLarge(true);
    if (isFirst) {
      setLoading(false);
    } else {
      setLoadingMore(false);
    }
    isFetchingRef.current = false;
    return true;
  }

  if (status === 416) {
    observerRef.current?.disconnect();
    if (isFirst) {
      setLoading(false);
    } else {
      setLoadingMore(false);
    }
    isFetchingRef.current = false;
    return true;
  }

  return false;
}

function appendTextPreviewContent(
  params: {
    detectedFileType: DetectedFileType;
    safeText: string;
    byteOffset: number;
    currentChunkLength: number;
    csvDelimiterRef: React.MutableRefObject<string>;
    setTxtLines: React.Dispatch<React.SetStateAction<string[]>>;
    setCsvRows: React.Dispatch<React.SetStateAction<string[][]>>;
    setTextContent: React.Dispatch<React.SetStateAction<string>>;
  },
): void {
  const {
    detectedFileType,
    safeText,
    byteOffset,
    currentChunkLength,
    csvDelimiterRef,
    setTxtLines,
    setCsvRows,
    setTextContent,
  } = params;

  if (!safeText) {
    return;
  }

  if (detectedFileType === 'text') {
    const newLines = safeText.split('\n');
    if (newLines.at(-1) === '') {
      newLines.pop();
    }
    setTxtLines(prev => [...prev, ...newLines]);
    return;
  }

  if (detectedFileType === 'csv') {
    if (byteOffset === currentChunkLength) {
      csvDelimiterRef.current = detectCsvDelimiter(safeText);
    }
    const newLines = safeText.split('\n').filter(line => line.trim().length > 0);
    setCsvRows(prev => [...prev, ...newLines.map((line) => parseCsvLine(line, csvDelimiterRef.current))]);
    return;
  }

  setTextContent(prev => prev + safeText);
}

function parseCsvLine(line: string, delimiter: string): string[] {
  const parsed = Papa.parse<string[]>(line, {
    header: false,
    skipEmptyLines: false,
    dynamicTyping: false,
    delimiter,
    quoteChar: '"',
    escapeChar: '"',
  });

  const row = parsed.data[0];
  if (Array.isArray(row)) {
    return row.map((cell) => (typeof cell === 'string' ? cell.trim() : String(cell ?? '').trim()));
  }

  return line.split(delimiter).map((cell) => cell.trim());
}

function detectCsvDelimiter(sampleText: string): string {
  const lines = sampleText
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .slice(0, 5);

  if (lines.length === 0) {
    return ',';
  }

  let bestDelimiter = ',';
  let bestScore = -1;

  for (const delimiter of CSV_DELIMITER_CANDIDATES) {
    const columnCounts = lines.map((line) => {
      const parsed = Papa.parse<string[]>(line, {
        header: false,
        skipEmptyLines: false,
        dynamicTyping: false,
        delimiter,
        quoteChar: '"',
        escapeChar: '"',
      });

      const row = parsed.data[0];
      return Array.isArray(row) ? row.length : 1;
    });

    const minColumns = Math.min(...columnCounts);
    const maxColumns = Math.max(...columnCounts);
    const averageColumns =
      columnCounts.reduce((sum, count) => sum + count, 0) / columnCounts.length;

    if (averageColumns <= 1) {
      continue;
    }

    const consistencyBonus = maxColumns === minColumns ? 100 : 0;
    const score = consistencyBonus + averageColumns;

    if (score > bestScore) {
      bestScore = score;
      bestDelimiter = delimiter;
    }
  }

  return bestDelimiter;
}

function computeRotateFitScale(
  rotationDeg: number,
  naturalSize: { width: number; height: number },
  viewportSize: { width: number; height: number },
): number {
  const { width: naturalWidth, height: naturalHeight } = naturalSize;
  const { width: viewportWidth, height: viewportHeight } = viewportSize;
  if (naturalWidth <= 0 || naturalHeight <= 0 || viewportWidth <= 0 || viewportHeight <= 0) {
    return 1;
  }

  const normalizedRotation = ((rotationDeg % 360) + 360) % 360;
  const isQuarterTurn = normalizedRotation === 90 || normalizedRotation === 270;
  const rotatedWidth = isQuarterTurn ? naturalHeight : naturalWidth;
  const rotatedHeight = isQuarterTurn ? naturalWidth : naturalHeight;
  const fitScale = Math.min(viewportWidth / rotatedWidth, viewportHeight / rotatedHeight);
  return Number.isFinite(fitScale) && fitScale > 0 ? fitScale : 1;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

type ImageScaleMode = 'fit' | 'actual' | 'custom';
type ImageBaseMode = 'fit' | 'actual';

type DetectedFileType = 'pdf' | 'image' | 'markdown' | 'csv' | 'text' | 'office' | 'unknown';

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
  const [imageScaleMode, setImageScaleMode] = useState<ImageScaleMode>('fit');
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
    
    if (mime === 'text/plain') return 'text';

    const extension = fileName.split('.').pop()?.toLowerCase() || '';
    
    if (extension === 'pdf') return 'pdf';
    if (['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].includes(extension)) {
      return isLocalSource ? 'office' : 'pdf';
    }
    if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(extension)) return 'image';
    if (['md', 'markdown'].includes(extension)) return 'markdown';
    if (extension === 'csv') return 'csv';
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
      setImageScaleMode('fit');
    } else {
      setImageBaseMode('actual');
      setImageScaleMode('actual');
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
    setImageScale(nextScale);
    setImageScaleMode('custom');
  }, [clampImagePan]);

  const handleImageWheel = useCallback((event: ReactWheelEvent<HTMLDivElement>) => {
    if (imageLoadError) {
      return;
    }

    event.preventDefault();

    const currentScale = imageScaleRef.current;
    const zoomFactor = Math.exp(-event.deltaY * 0.0015);
    const nextScale = clamp(currentScale * zoomFactor, 0.25, 6);
    if (nextScale === currentScale) {
      return;
    }

    const rect = event.currentTarget.getBoundingClientRect();
    const cursorX = event.clientX - rect.left - rect.width / 2;
    const cursorY = event.clientY - rect.top - rect.height / 2;
    applyImageScale(nextScale, cursorX, cursorY);
  }, [applyImageScale, imageLoadError]);

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
    setImageBaseMode('fit');
    setImageScaleMode('fit');
    setImageScale(1);
    imageScaleRef.current = 1;
    handleImagePanReset();
  }, [handleImagePanReset]);

  const toggleImageScaleMode = useCallback(() => {
    if (imageBaseMode === 'fit') {
      setImageBaseMode('actual');
      setImageScaleMode('actual');
    } else {
      setImageBaseMode('fit');
      setImageScaleMode('fit');
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

          if (isTooLargeToPreview && ['text', 'markdown', 'csv'].includes(detectedFileType)) {
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

        if (['markdown', 'csv', 'text'].includes(detectedFileType)) {
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
      setImageScaleMode('fit');
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
      handleImagePanReset();
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
                const nextScale = clamp(imageScaleRef.current - 0.25, 0.25, 6);
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
                const nextScale = clamp(imageScaleRef.current + 0.25, 0.25, 6);
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
              onClick={toggleImageScaleMode}
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
