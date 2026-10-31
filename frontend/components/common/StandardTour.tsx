"use client";

import { ConfigProvider, Tour, type TourProps } from "antd";
import { useEffect, useId } from "react";

import "./standard-tour.css";

/** Measured explanatory tour; callers own workflow targets and completion. */
export function StandardTour(props: TourProps) {
  const { current, open } = props;
  const instanceClass = `standard-tour-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;

  useEffect(() => {
    if (!open) return;
    let frame = 0;
    let attempts = 0;
    let observer: MutationObserver | undefined;
    let resizeObserver: ResizeObserver | undefined;
    const alignToViewport = () => {
      const root = document.querySelector<HTMLElement>(
        `.${instanceClass}.ant-tour`
      );
      if (!root) return;
      const bounds = root.getBoundingClientRect();
      const style = getComputedStyle(root);
      const offsetX =
        parseFloat(style.getPropertyValue("--tour-offset-x")) || 0;
      const offsetY =
        parseFloat(style.getPropertyValue("--tour-offset-y")) || 0;
      const x = bounds.x + offsetX;
      const y = bounds.y + offsetY;
      const shiftX =
        Math.max(16, Math.min(x, window.innerWidth - bounds.width - 16)) - x;
      const shiftY =
        Math.max(16, Math.min(y, window.innerHeight - bounds.height - 16)) - y;
      root
        .querySelectorAll<HTMLElement>(".ant-tour-panel, .ant-tour-arrow")
        .forEach((element) => {
          element.style.setProperty("--tour-clamp-x", `${shiftX}px`);
          element.style.setProperty("--tour-clamp-y", `${shiftY}px`);
        });
    };
    const schedule = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(alignToViewport);
    };
    const connect = () => {
      const root = document.querySelector<HTMLElement>(
        `.${instanceClass}.ant-tour`
      );
      if (!root && attempts++ < 120) {
        frame = window.requestAnimationFrame(connect);
        return;
      }
      if (!root) return;
      observer = new MutationObserver(schedule);
      observer.observe(root, {
        attributes: true,
        attributeFilter: ["style", "class"],
      });
      resizeObserver = new ResizeObserver(schedule);
      resizeObserver.observe(root);
      alignToViewport();
    };
    frame = window.requestAnimationFrame(connect);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    return () => {
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
      resizeObserver?.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
    };
  }, [instanceClass, current, open]);

  return (
    <ConfigProvider
      button={{ autoInsertSpace: false }}
      theme={{
        token: {
          fontFamily: '"HarmonyOS Sans SC", system-ui, sans-serif',
          colorPrimary: "#0067D1",
          colorText: "#191919",
          colorBorder: "#C9C9C9",
          borderRadius: 4,
          borderRadiusLG: 6,
          sizePopupArrow: 16,
        },
      }}
    >
      <Tour
        {...props}
        rootClassName={`standard-tour ${instanceClass} ${props.rootClassName ?? ""}`}
        closable={false}
        disabledInteraction
        indicatorsRender={() => null}
        mask={{ color: "rgba(0, 0, 0, 0.231372549)" }}
        styles={{
          section: {
            padding: 16,
            minHeight: 174,
            borderRadius: 6,
            boxShadow: "0 8px 24px 0 rgba(0, 0, 0, 0.16)",
          },
          header: { padding: 0, width: "100%", marginBottom: 8 },
          title: {
            fontSize: 16,
            lineHeight: "24px",
            fontWeight: 500,
            letterSpacing: 0,
            color: "#191919",
          },
          description: {
            padding: 0,
            fontSize: 14,
            lineHeight: "22px",
            fontWeight: 400,
            letterSpacing: 0,
            color: "#777777",
          },
          footer: { padding: 0, marginTop: 16 },
          indicators: { display: "none" },
          actions: { display: "flex", gap: 8 },
        }}
      />
    </ConfigProvider>
  );
}
