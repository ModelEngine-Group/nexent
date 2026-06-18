import Papa from 'papaparse';
import type { DetectedFileType } from '@/types/file';
import log from '@/lib/logger';

export const CHUNK_SIZE = 128 * 1024;
export const CSV_ROW_HEIGHT = 40;
export const TEXT_RENDER_BLOCK_SIZE = 200;
export const CSV_DELIMITER_CANDIDATES = [',', ';', '\t', '|'] as const;
export const CHARSET_PATTERN = /charset\s*=\s*([^;\s]+)/i;
export const CONTENT_RANGE_PATTERN = /bytes (\d+)-(\d+)\/(\d+)/;
export const INVALID_CONTAINER_TAGS = new Set(['head', 'style', 'script', 'link', 'meta']);

export function isValidContainerElement(el: Element | null): el is HTMLDivElement {
  if (!(el instanceof HTMLDivElement)) {
    return false;
  }
  if (!el.isConnected) {
    return false;
  }
  const tagName = el.tagName.toLowerCase();
  return !INVALID_CONTAINER_TAGS.has(tagName);
}

export function normalizeCharsetLabel(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'gbk' || normalized === 'gb2312' || normalized === 'cp936') {
    return 'gb18030';
  }
  return normalized;
}

export function extractCharsetFromContentType(contentType: string | null): string | null {
  if (!contentType) return null;
  const match = CHARSET_PATTERN.exec(contentType);
  if (!match?.[1]) return null;
  return normalizeCharsetLabel(match[1].replaceAll(/^"|"$/g, ''));
}

export function updateChunkRangeState(
  contentRange: string | null,
  byteLength: number,
  byteOffsetRef: { current: number },
  totalBytesRef: { current: number | null },
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

export function ensurePreviewTextDecoder(
  contentType: string | null,
  textDecoderRef: { current: TextDecoder | null },
  decoderEncodingRef: { current: string | null },
  decoderHasExplicitCharsetRef: { current: boolean },
  decoderAllowGbFallbackRef: { current: boolean },
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
  textDecoderRef.current = new TextDecoder('utf-8', { fatal: true });
  decoderEncodingRef.current = 'utf-8';
  decoderHasExplicitCharsetRef.current = false;
  decoderAllowGbFallbackRef.current = true;
}

export function decodePreviewChunk(
  buf: ArrayBuffer,
  hasMore: boolean,
  textDecoderRef: { current: TextDecoder | null },
  decoderEncodingRef: { current: string | null },
  decoderAllowGbFallbackRef: { current: boolean },
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

export async function decodeLocalTextFile(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buf);
  } catch {
    return new TextDecoder('gb18030').decode(buf);
  }
}

export function splitPreviewSafeText(
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

export function shouldStopFetchingChunk(
  activeSessionId: number,
  currentSessionId: number,
): boolean {
  return activeSessionId !== currentSessionId;
}

export function handlePreviewChunkBoundaryResponse(
  status: number,
  isFirst: boolean,
  setServerTooLarge: React.Dispatch<React.SetStateAction<boolean>>,
  setLoading: React.Dispatch<React.SetStateAction<boolean>>,
  setLoadingMore: React.Dispatch<React.SetStateAction<boolean>>,
  observerRef: { current: IntersectionObserver | null },
  isFetchingRef: { current: boolean },
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

export function appendTextPreviewContent(
  params: {
    detectedFileType: DetectedFileType;
    safeText: string;
    byteOffset: number;
    currentChunkLength: number;
    csvDelimiterRef: { current: string };
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

export function parseCsvLine(line: string, delimiter: string): string[] {
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

export function detectCsvDelimiter(sampleText: string): string {
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

export function computeRotateFitScale(
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

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function ignoreAbortError(error: unknown): boolean {
  const errorName = typeof error === 'object' && error !== null && 'name' in error
    ? String((error as { name?: unknown }).name)
    : '';
  const errorMessage = typeof error === 'object' && error !== null && 'message' in error
    ? String((error as { message?: unknown }).message)
    : '';

  return errorName === 'AbortException' || errorMessage.includes('TextLayer task cancelled');
}

export function getPageWrapperStyle(
  isRendered: boolean,
  hasMeasuredHeight: boolean,
  placeholderHeight: number,
  placeholderWidth: number,
) {
  if (!isRendered) {
    return { height: placeholderHeight, width: placeholderWidth };
  }

  if (hasMeasuredHeight) {
    return undefined;
  }

  return { minHeight: placeholderHeight, width: placeholderWidth };
}
