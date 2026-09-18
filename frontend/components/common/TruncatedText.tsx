import React, { useEffect, useRef, useState } from "react";
import { Tooltip } from "antd";
import type { TooltipProps } from "antd";

type TruncatedTextTag = "div" | "p" | "span" | "h1" | "h2" | "h3" | "h4";

export interface TruncatedTextProps {
  /** The full text: rendered clamped, and repeated inside the tooltip. */
  text: string;
  /** Classes for the clamped element (typography, width, margins). */
  className?: string;
  /** Element to render. Defaults to a div. */
  as?: TruncatedTextTag;
  /** Forwarded to the antd Tooltip. */
  placement?: TooltipProps["placement"];
}

/**
 * Single-line clamped text that reveals its full value on hover.
 *
 * antd's Tooltip is used instead of the native `title` attribute: `title` is
 * shown by the browser after an unpredictable delay, cannot be styled, and
 * pops up even when the text is not clipped.
 *
 * The tooltip is attached only once the text actually overflows its box, so
 * short values stay quiet. Overflow is measured from the DOM rather than
 * inferred from the string length, because the box is fluid: the same text is
 * clipped or not depending on the width it is given.
 */
export const TruncatedText: React.FC<TruncatedTextProps> = ({
  text,
  className,
  as = "div",
  placement,
}) => {
  const elementRef = useRef<HTMLElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return;

    const measure = () => {
      // The 1px slack absorbs sub-pixel rounding, which would otherwise report
      // an overflow for text rendered exactly at the available width.
      setIsTruncated(element.scrollWidth > element.clientWidth + 1);
    };

    measure();
    // The box is fluid, so resizing the viewport can clip a value that
    // previously fitted, without any React state change to observe.
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, className]);

  const Element = as as React.ElementType;
  const element = (
    <Element ref={elementRef} className={className}>
      {text}
    </Element>
  );

  if (!isTruncated) return element;

  return (
    <Tooltip title={text} placement={placement}>
      {element}
    </Tooltip>
  );
};
