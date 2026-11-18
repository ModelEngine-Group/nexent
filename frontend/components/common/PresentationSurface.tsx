// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import PreviewControls from "./PreviewControls";
import styles from "./DocumentPreview.module.css";
export default function PresentationSurface({
  size,
  slides,
}: {
  size: { width: number; height: number };
  slides: ReactNode[];
}) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [navigation, setNavigation] = useState(false);
  const [custom, setCustom] = useState<number | null>(null);
  const [available, setAvailable] = useState({ width: 0, height: 0 });
  const [railWidth, setRailWidth] = useState(200);
  const viewportRef = useRef<HTMLDivElement>(null);
  const railRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const node = viewportRef.current;
    if (!node) return;
    const observer = new ResizeObserver(() =>
      setAvailable({
        width: node.clientWidth - 48,
        height: node.clientHeight - 48,
      })
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const node = railRef.current;
    if (!node) return;
    const observer = new ResizeObserver(() =>
      setRailWidth(Math.max(40, node.clientWidth - 42))
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [navigation]);
  const fit =
    Math.min(available.width / size.width, available.height / size.height, 1) ||
    1;
  const zoom = custom ?? fit;
  return (
    <div className={styles.reader}>
      <div className={styles.slidesLayout}>
        {navigation && (
          <nav
            ref={railRef}
            className={styles.slideRail}
            aria-label={t("filePreview.pdf.thumbnails")}
          >
            {slides.map((slide, index) => (
              <button
                key={index}
                type="button"
                onClick={() => setPage(index + 1)}
                aria-current={page === index + 1 ? "page" : undefined}
                aria-label={t("filePreview.office.slide", { index: index + 1 })}
              >
                <div
                  style={{
                    position: "relative",
                    width: railWidth,
                    height: (railWidth * size.height) / size.width,
                    overflow: "hidden",
                    background: "white",
                    marginBottom: 6,
                  }}
                >
                  <div
                    className={styles.slideCanvas}
                    style={{
                      width: size.width,
                      height: size.height,
                      transform: `scale(${railWidth / size.width})`,
                      transformOrigin: "top left",
                    }}
                  >
                    {slide}
                  </div>
                </div>
                {index + 1}
              </button>
            ))}
          </nav>
        )}
        <div ref={viewportRef} className={styles.slideViewport}>
          <div
            style={{
              position: "relative",
              width: size.width * zoom,
              height: size.height * zoom,
              margin: "auto",
            }}
          >
            <div
              className={styles.slideCanvas}
              style={{
                width: size.width,
                height: size.height,
                transform: `scale(${zoom})`,
                transformOrigin: "top left",
              }}
            >
              {slides[page - 1]}
            </div>
          </div>
        </div>
      </div>
      <PreviewControls
        zoom={zoom}
        onZoom={setCustom}
        onFit={() => setCustom(null)}
        page={page}
        pages={slides.length}
        onPage={setPage}
        onToggleNavigation={() => setNavigation((value) => !value)}
        navigationOpen={navigation}
      />
    </div>
  );
}
