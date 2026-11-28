// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useTranslation } from "react-i18next";
import { InputNumber } from "antd";
import {
  ChevronLeft,
  ChevronRight,
  Maximize2,
  Menu,
  Minimize2,
  Minus,
  PanelLeft,
  Plus,
} from "lucide-react";
import styles from "./DocumentPreview.module.css";
interface Props {
  zoom: number;
  onZoom: (value: number) => void;
  onFit?: () => void;
  page?: number;
  pages?: number;
  onPage?: (page: number) => void;
  onToggleNavigation?: () => void;
  navigationOpen?: boolean;
  /** Optional editable page number; replaces the plain "page / pages" label. */
  pageInput?: { value: number; onChange: (page: number) => void };
  onToggleOutline?: () => void;
  outlineOpen?: boolean;
  onToggleThumbnails?: () => void;
  thumbnailsOpen?: boolean;
  zoomStep?: number;
  minZoom?: number;
  maxZoom?: number;
  showZoomPercentage?: boolean;
  showActualSize?: boolean;
  fitToggle?: { active: boolean; label: string; onToggle: () => void };
}
export default function PreviewControls({
  zoom,
  onZoom,
  onFit,
  page,
  pages,
  onPage,
  onToggleNavigation,
  navigationOpen,
  pageInput,
  onToggleOutline,
  outlineOpen,
  onToggleThumbnails,
  thumbnailsOpen,
  zoomStep = 0.1,
  minZoom = 0.25,
  maxZoom = 3,
  showZoomPercentage = true,
  showActualSize = true,
  fitToggle,
}: Props) {
  const { t } = useTranslation();
  return (
    <div className={styles.controls}>
      {onToggleThumbnails && (
        <button
          type="button"
          onClick={onToggleThumbnails}
          aria-label={t("filePreview.pdf.thumbnails")}
          aria-expanded={thumbnailsOpen}
        >
          <PanelLeft size={16} />
        </button>
      )}
      {onToggleOutline && (
        <button
          type="button"
          onClick={onToggleOutline}
          aria-label={
            outlineOpen
              ? t("filePreview.pdf.hideOutline")
              : t("filePreview.pdf.showOutline")
          }
          aria-expanded={outlineOpen}
        >
          <Menu size={16} />
        </button>
      )}
      {(onToggleNavigation || onToggleOutline || onToggleThumbnails) && (
        <div className={styles.controlsDivider} />
      )}
      {page !== undefined && pages !== undefined && onPage && (
        <>
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
            aria-label={t("filePreview.pdf.previousPage")}
          >
            <ChevronLeft size={16} />
          </button>
          {pageInput ? (
            <span className={styles.pageInput}>
              <InputNumber
                size="small"
                min={1}
                max={pages}
                value={pageInput.value}
                controls={false}
                onChange={(value) => {
                  if (value) pageInput.onChange(value);
                }}
                title={t("filePreview.pdf.goToPage")}
              />
              <span>/ {pages}</span>
            </span>
          ) : (
            <span>
              {page} / {pages}
            </span>
          )}
          <button
            type="button"
            disabled={page >= pages}
            onClick={() => onPage(page + 1)}
            aria-label={t("filePreview.pdf.nextPage")}
          >
            <ChevronRight size={16} />
          </button>
        </>
      )}
      <button
        type="button"
        onClick={() => onZoom(Math.max(minZoom, zoom - zoomStep))}
        disabled={zoom <= minZoom}
        aria-label={t("filePreview.reader.zoomOut")}
      >
        <Minus size={16} />
      </button>
      {showZoomPercentage && <span>{Math.round(zoom * 100)}%</span>}
      <button
        type="button"
        onClick={() => onZoom(Math.min(maxZoom, zoom + zoomStep))}
        disabled={zoom >= maxZoom}
        aria-label={t("filePreview.reader.zoomIn")}
      >
        <Plus size={16} />
      </button>
      {fitToggle && (
        <button
          type="button"
          onClick={fitToggle.onToggle}
          aria-label={fitToggle.label}
          title={fitToggle.label}
          aria-pressed={fitToggle.active}
        >
          {fitToggle.active ? <Maximize2 size={16} /> : <Minimize2 size={16} />}
        </button>
      )}
      {onFit && (
        <button type="button" onClick={onFit}>
          {t("filePreview.reader.fit")}
        </button>
      )}
      {showActualSize && (
        <button type="button" onClick={() => onZoom(1)}>
          {t("filePreview.reader.actual")}
        </button>
      )}
    </div>
  );
}
