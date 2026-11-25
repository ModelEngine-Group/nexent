// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import PreviewControls from "./PreviewControls";
import styles from "./DocumentPreview.module.css";
export default function DocumentPages({ children }: { children: ReactNode }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 816, height: 1000 });
  const [available, setAvailable] = useState(0);
  const [custom, setCustom] = useState<number | null>(null);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const scale = custom ?? Math.min(1, (available || size.width) / size.width);
  useEffect(() => {
    const viewport = viewportRef.current,
      content = contentRef.current;
    if (!viewport || !content) return;
    const update = () => {
      setAvailable(Math.max(1, viewport.clientWidth - 48));
      setSize({
        width: content.offsetWidth || 816,
        height: content.offsetHeight || 1000,
      });
      setPages(Math.max(1, content.querySelectorAll("section.docx").length));
    };
    const resize = new ResizeObserver(update);
    resize.observe(viewport);
    resize.observe(content);
    const mutation = new MutationObserver(update);
    mutation.observe(content, { childList: true, subtree: true });
    update();
    return () => {
      resize.disconnect();
      mutation.disconnect();
    };
  }, []);
  return (
    <div className={styles.reader}>
      <div
        ref={viewportRef}
        className={styles.docViewport}
        onScroll={() => {
          const viewport = viewportRef.current;
          if (!viewport) return;
          const nodes = Array.from(
            contentRef.current?.querySelectorAll("section.docx") ?? []
          );
          let index = 0;
          nodes.forEach((node, i) => {
            if (
              node.getBoundingClientRect().top <=
              viewport.getBoundingClientRect().top + 60
            )
              index = i;
          });
          setPage(index + 1);
        }}
      >
        <div
          style={{
            position: "relative",
            width: size.width * scale,
            height: size.height * scale,
            margin: "0 auto",
          }}
        >
          <div
            ref={contentRef}
            className={styles.docPage}
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              width: "max-content",
              transform: `scale(${scale})`,
              transformOrigin: "top left",
            }}
          >
            {children}
          </div>
        </div>
      </div>
      <PreviewControls
        zoom={scale}
        onZoom={setCustom}
        onFit={() => setCustom(null)}
        page={pages > 1 ? page : undefined}
        pages={pages > 1 ? pages : undefined}
        onPage={(next) => {
          const viewport = viewportRef.current;
          const target =
            contentRef.current?.querySelectorAll("section.docx")[next - 1];
          if (viewport && target)
            viewport.scrollTo({
              top:
                target.getBoundingClientRect().top -
                viewport.getBoundingClientRect().top +
                viewport.scrollTop -
                24,
            });
          setPage(next);
        }}
      />
    </div>
  );
}
