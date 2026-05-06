// File type definitions shared across file preview components

export type DetectedFileType = 'pdf' | 'image' | 'markdown' | 'csv' | 'text' | 'office' | 'unknown';

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
}

export type ScaleMode = 'fit-width' | 'fit-page' | 'actual-size' | 'custom';

export interface ViewportAnchor {
  page: number;
  pageOffsetRatio: number;
}
