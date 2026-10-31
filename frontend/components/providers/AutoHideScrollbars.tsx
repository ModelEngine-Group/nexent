// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useEffect } from "react";

const HIDE_DELAY = 600;

/** Tracks native scroll containers, including portals, without changing layout. */
export function AutoHideScrollbars() {
  useEffect(() => {
    const root = document.documentElement;
    const timers = new Map<Element, ReturnType<typeof setTimeout>>();
    root.classList.add("auto-hide-scrollbars");

    const onScroll = (event: Event) => {
      const target =
        event.target === document ? document.scrollingElement : event.target;
      if (!(target instanceof Element)) return;

      clearTimeout(timers.get(target));
      target.setAttribute("data-scrollbar-scrolling", "");
      timers.set(
        target,
        setTimeout(() => {
          target.removeAttribute("data-scrollbar-scrolling");
          timers.delete(target);
        }, HIDE_DELAY)
      );
    };

    document.addEventListener("scroll", onScroll, {
      capture: true,
      passive: true,
    });

    return () => {
      document.removeEventListener("scroll", onScroll, true);
      root.classList.remove("auto-hide-scrollbars");
      timers.forEach((timer, target) => {
        clearTimeout(timer);
        target.removeAttribute("data-scrollbar-scrolling");
      });
      timers.clear();
    };
  }, []);

  return null;
}
