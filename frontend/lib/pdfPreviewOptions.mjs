// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { BASE_PATH } from "../base-path.mjs";

export const PDF_DOCUMENT_OPTIONS = {
  rangeChunkSize: 65536,
  cMapUrl: `${BASE_PATH}/pdfjs/cmaps/`,
  cMapPacked: true,
  standardFontDataUrl: `${BASE_PATH}/pdfjs/standard_fonts/`,
};
