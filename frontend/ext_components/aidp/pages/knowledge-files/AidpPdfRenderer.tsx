// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { PdfViewer } from "@/components/common/PdfViewer";
import type { PdfViewerProps } from "@/types/file";

export function AidpPdfRenderer(props: PdfViewerProps) {
  return <PdfViewer {...props} enableThumbnails />;
}
