// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useEffect,
  useId,
  useMemo,
  useState,
  type ComponentProps,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/common/Button";
import {
  Popover,
  PopoverAnchor,
  PopoverArrow,
  PopoverContent,
} from "@/components/common/Popover";
import { cn } from "@/lib/utils";

const DEFAULT_SCROLL_OPTIONS: ScrollIntoViewOptions = { block: "nearest" };

export interface TourStep {
  title: ReactNode;
  description?: ReactNode;
  target?: HTMLElement | null | (() => HTMLElement | null);
  placement?:
    | "right"
    | "left"
    | "top"
    | "bottom"
    | "topLeft"
    | "topRight"
    | "bottomLeft"
    | "bottomRight";
  className?: string;
  style?: CSSProperties;
  prevButtonProps?: ComponentProps<typeof Button>;
  nextButtonProps?: ComponentProps<typeof Button>;
}
export interface CreationGuideTourProps {
  open?: boolean;
  current?: number;
  defaultCurrent?: number;
  steps: TourStep[];
  onChange?: (current: number) => void;
  onClose?: (current: number) => void;
  onFinish?: () => void;
  rootClassName?: string;
  actionsRender?: (actions: ReactNode[]) => ReactNode;
  gap?: { offset?: number | [number, number]; radius?: number };
  scrollIntoViewOptions?: boolean | ScrollIntoViewOptions;
}

/** Project guide behavior over Radix positioning/focus; callers own completion. */
export function CreationGuideTour({
  open = false,
  current,
  defaultCurrent = 0,
  steps,
  onChange,
  onClose,
  onFinish,
  rootClassName,
  actionsRender,
  gap,
  scrollIntoViewOptions = DEFAULT_SCROLL_OPTIONS,
}: CreationGuideTourProps) {
  const { t } = useTranslation("common");
  const [localCurrent, setLocalCurrent] = useState(defaultCurrent);
  const index = Math.max(
    0,
    Math.min(current ?? localCurrent, steps.length - 1)
  );
  const step = steps[index];
  const id = useId().replaceAll(":", "");
  const [rect, setRect] = useState({ x: 0, y: 0, width: 0, height: 0 });
  useEffect(() => {
    if (!open || !step) return;
    const target =
      typeof step.target === "function" ? step.target() : step.target;
    target?.scrollIntoView?.(scrollIntoViewOptions);
    const measure = () => {
      const box = target?.getBoundingClientRect();
      setRect(
        box && box.width && box.height
          ? { x: box.x, y: box.y, width: box.width, height: box.height }
          : {
              x: window.innerWidth / 2,
              y: window.innerHeight / 2,
              width: 0,
              height: 0,
            }
      );
    };
    // The state is a snapshot of externally owned DOM geometry.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    measure();
    const observer = new ResizeObserver(measure);
    if (target) observer.observe(target);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open, step, scrollIntoViewOptions]);
  const virtualRef = useMemo(
    () => ({
      current: {
        getBoundingClientRect: () =>
          new DOMRect(rect.x, rect.y, rect.width, rect.height),
      },
    }),
    [rect]
  );
  if (!open || !step) return null;
  const setCurrent = (next: number) => {
    if (current === undefined) setLocalCurrent(next);
    onChange?.(next);
  };
  const close = () => onClose?.(index);
  const placement = step.placement ?? "bottom";
  const side = placement.startsWith("top")
    ? "top"
    : placement.startsWith("bottom")
      ? "bottom"
      : (placement as "right" | "left");
  const align = placement.endsWith("Left")
    ? "start"
    : placement.endsWith("Right")
      ? "end"
      : "center";
  const [gapX, gapY] = Array.isArray(gap?.offset)
    ? gap.offset
    : [gap?.offset ?? 6, gap?.offset ?? 6];
  const actions = [
    index > 0 && (
      <Button
        key="previous"
        variant="outline"
        size="sm"
        {...step.prevButtonProps}
        onClick={(event) => {
          step.prevButtonProps?.onClick?.(event);
          if (!event.defaultPrevented) setCurrent(index - 1);
        }}
      >
        {step.prevButtonProps?.children ?? t("tour.previous")}
      </Button>
    ),
    <Button
      key="next"
      size="sm"
      {...step.nextButtonProps}
      data-ui-tour-next=""
      onClick={(event) => {
        step.nextButtonProps?.onClick?.(event);
        if (event.defaultPrevented) return;
        if (index === steps.length - 1) {
          onFinish?.();
          close();
        } else setCurrent(index + 1);
      }}
    >
      {step.nextButtonProps?.children ??
        t(index === steps.length - 1 ? "tour.finish" : "tour.next")}
    </Button>,
  ];
  return (
    <>
      {createPortal(
        <div
          data-ui-tour-mask=""
          className="fixed inset-0 z-[var(--ui-layer-popover)]"
          aria-hidden="true"
        >
          <svg className="size-full">
            <defs>
              <mask id={`tour-mask-${id}`}>
                <rect width="100%" height="100%" fill="white" />
                {rect.width > 0 && (
                  <rect
                    x={rect.x - gapX}
                    y={rect.y - gapY}
                    width={Math.max(0, rect.width + gapX * 2)}
                    height={Math.max(0, rect.height + gapY * 2)}
                    rx={gap?.radius ?? 8}
                    fill="black"
                  />
                )}
              </mask>
            </defs>
            <rect
              width="100%"
              height="100%"
              fill="rgb(0 0 0 / 0.24)"
              mask={`url(#tour-mask-${id})`}
            />
          </svg>
        </div>,
        document.body
      )}
      <Popover
        open
        modal
        onOpenChange={(next) => {
          if (!next) close();
        }}
      >
        <PopoverAnchor virtualRef={virtualRef} />
        <PopoverContent
          data-ui-tour=""
          side={side}
          align={align}
          sideOffset={12}
          collisionPadding={16}
          className={cn(
            "standard-tour z-[var(--ui-layer-tour)] min-h-[174px] max-w-[calc(100vw-2rem)] p-4",
            rootClassName,
            step.className
          )}
          style={step.style}
          aria-labelledby={`tour-title-${id}`}
          aria-describedby={
            step.description ? `tour-description-${id}` : undefined
          }
          onInteractOutside={(event) => event.preventDefault()}
          onEscapeKeyDown={(event) => {
            event.preventDefault();
            event.stopPropagation();
            close();
          }}
        >
          <div
            data-ui-tour-title=""
            id={`tour-title-${id}`}
            className="mb-2 text-base font-medium"
          >
            {step.title}
          </div>
          <div
            data-ui-tour-description=""
            id={`tour-description-${id}`}
            className="text-sm leading-[22px] text-muted-foreground"
          >
            {step.description}
          </div>
          <div data-ui-tour-actions="" className="mt-4 flex justify-end gap-2">
            {actionsRender ? actionsRender(actions) : actions}
          </div>
          <PopoverArrow
            data-ui-tour-arrow=""
            className="fill-popover"
            width={16}
            height={8}
          />
        </PopoverContent>
      </Popover>
    </>
  );
}
