// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useTranslation } from "react-i18next";
import {
  ChevronLeft,
  ChevronRight,
  Minus,
  Plus,
  PanelLeft,
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
}: Props) {
  const { t } = useTranslation();
  return (
    <div className={styles.controls}>
      {onToggleNavigation && (
        <button
          type="button"
          onClick={onToggleNavigation}
          aria-label={t("filePreview.reader.navigation")}
          aria-expanded={navigationOpen}
        >
          <PanelLeft size={16} />
        </button>
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
          <span>
            {page} / {pages}
          </span>
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
        onClick={() => onZoom(Math.max(0.25, zoom - 0.1))}
        disabled={zoom <= 0.25}
        aria-label={t("filePreview.reader.zoomOut")}
      >
        <Minus size={16} />
      </button>
      <span>{Math.round(zoom * 100)}%</span>
      <button
        type="button"
        onClick={() => onZoom(Math.min(3, zoom + 0.1))}
        disabled={zoom >= 3}
        aria-label={t("filePreview.reader.zoomIn")}
      >
        <Plus size={16} />
      </button>
      {onFit && (
        <button type="button" onClick={onFit}>
          {t("filePreview.reader.fit")}
        </button>
      )}
      <button type="button" onClick={() => onZoom(1)}>
        {t("filePreview.reader.actual")}
      </button>
    </div>
  );
}
