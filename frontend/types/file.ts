// File type definitions shared across file preview components

// `stream` is a document whose format is only known from the response (AIDP
// serves the original bytes for docx/xlsx/pptx/pdf/txt and a PDF conversion for
// every other format), so the stream viewer resolves the renderer itself.
export type DetectedFileType = 'pdf' | 'image' | 'markdown' | 'csv' | 'text' | 'html' | 'office' | 'stream' | 'unknown';

export type ImageBaseMode = 'fit' | 'actual';

// PDF Viewer types
export interface OutlineItem {
  title: string;
  dest: string | null;
  items?: OutlineItem[];
  pageNumber?: number;
}

export interface PdfViewerProps {
  url: string;
  fileName: string;
  /**
   * Zoom the viewer starts with. Defaults to `fit-page`, which shows a whole
   * page; `fit-width` suits surfaces that are wider than a document page, such
   * as the full-screen preview.
   */
  initialScaleMode?: ScaleMode;
}

export type ScaleMode = 'fit-width' | 'fit-page' | 'actual-size' | 'custom';

export interface ViewportAnchor {
  page: number;
  pageOffsetRatio: number;
}
