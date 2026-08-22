"use client";

import * as React from "react";
import { ScrollArea as ScrollAreaPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

const ScrollArea = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root>
>(({ className, children, ...props }, ref) => (
  <ScrollAreaPrimitive.Root
    ref={ref}
    className={cn("relative overflow-hidden", className)}
    {...props}
  >
    <ScrollAreaPrimitive.Viewport className="h-full w-full rounded-[inherit]">
      {children}
    </ScrollAreaPrimitive.Viewport>
    <ScrollBar />
    <ScrollAreaPrimitive.Corner />
  </ScrollAreaPrimitive.Root>
));
ScrollArea.displayName = ScrollAreaPrimitive.Root.displayName;

// StaticScrollArea that prevents auto-scrolling while using Radix UI
const StaticScrollArea = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root>
>(({ className, children, ...props }, ref) => {
  const [viewportElement, setViewportElement] =
    React.useState<HTMLDivElement | null>(null);
  const scrollPositionRef = React.useRef<number>(0);
  const lastUserInteractionTimeRef = React.useRef<number>(0);
  const lastClickTimeRef = React.useRef<number>(0);
  const isRestoringRef = React.useRef<boolean>(false);

  // Save current scroll position
  const saveScrollPosition = React.useCallback(() => {
    if (viewportElement && !isRestoringRef.current) {
      scrollPositionRef.current = viewportElement.scrollTop;
    }
  }, [viewportElement]);

  // Restore scroll position to saved value
  const restoreScrollPosition = React.useCallback(() => {
    if (viewportElement && !isRestoringRef.current) {
      const targetPosition = scrollPositionRef.current;
      const currentPosition = viewportElement.scrollTop;
      if (currentPosition !== targetPosition) {
        isRestoringRef.current = true;
        viewportElement.scrollTop = targetPosition;
        // Briefly mark as restoring to prevent triggering new scroll events
        setTimeout(() => {
          isRestoringRef.current = false;
        }, 50);
        return true;
      }
    }
    return false;
  }, [viewportElement]);

  // Determine if scroll is user-initiated based on timing
  const isUserInitiatedScroll = React.useCallback(() => {
    const now = Date.now();
    const timeSinceLastUserInteraction =
      now - lastUserInteractionTimeRef.current;
    const timeSinceLastClick = now - lastClickTimeRef.current;

    // If within 500ms of user interaction, consider it user scrolling
    if (timeSinceLastUserInteraction < 500) {
      return true;
    }

    // If within 100ms of a click, likely programmatic scrolling
    if (timeSinceLastClick < 100) {
      return false;
    }

    return false;
  }, []);

  // Handle scroll events
  const handleScroll = React.useCallback(
    (e: Event) => {
      if (isRestoringRef.current) {
        return;
      }

      if (isUserInitiatedScroll()) {
        saveScrollPosition();
      } else {
        e.preventDefault();
        e.stopImmediatePropagation();
        restoreScrollPosition();
      }
    },
    [isUserInitiatedScroll, saveScrollPosition, restoreScrollPosition]
  );

  // Record user interaction timestamp
  const recordUserInteraction = React.useCallback(() => {
    lastUserInteractionTimeRef.current = Date.now();
  }, []);

  // Record click timestamp
  const recordClick = React.useCallback(() => {
    lastClickTimeRef.current = Date.now();
  }, []);

  // Listen for genuine user scroll interactions
  React.useEffect(() => {
    if (viewportElement) {
      const handleWheel = () => recordUserInteraction();
      const handleTouchStart = () => recordUserInteraction();
      const handleKeyDown = (e: KeyboardEvent) => {
        if (
          [
            "ArrowUp",
            "ArrowDown",
            "PageUp",
            "PageDown",
            "Home",
            "End",
          ].includes(e.key)
        ) {
          recordUserInteraction();
        }
      };

      viewportElement.addEventListener("wheel", handleWheel, { passive: true });
      viewportElement.addEventListener("touchstart", handleTouchStart, {
        passive: true,
      });
      viewportElement.addEventListener("keydown", handleKeyDown, {
        passive: true,
      });

      return () => {
        viewportElement.removeEventListener("wheel", handleWheel);
        viewportElement.removeEventListener("touchstart", handleTouchStart);
        viewportElement.removeEventListener("keydown", handleKeyDown);
      };
    }
  }, [viewportElement, recordUserInteraction]);

  // Listen for click events that might trigger programmatic scrolling
  React.useEffect(() => {
    if (viewportElement) {
      // Monitor document-wide clicks as they can happen anywhere
      document.addEventListener("click", recordClick, { capture: true });
      document.addEventListener("mousedown", recordClick, { capture: true });

      return () => {
        document.removeEventListener("click", recordClick, { capture: true });
        document.removeEventListener("mousedown", recordClick, {
          capture: true,
        });
      };
    }
  }, [viewportElement, recordClick]);

  // Listen for scroll events with highest priority interception
  React.useEffect(() => {
    if (viewportElement) {
      viewportElement.addEventListener("scroll", handleScroll, {
        passive: false,
        capture: true,
      });

      return () => {
        viewportElement.removeEventListener("scroll", handleScroll, {
          capture: true,
        });
      };
    }
  }, [viewportElement, handleScroll]);

  // Set viewport element reference
  const setViewportRef = React.useCallback((node: HTMLDivElement | null) => {
    setViewportElement(node);
    if (node) {
      setTimeout(() => {
        if (node) {
          scrollPositionRef.current = node.scrollTop;
        }
      }, 0);
    }
  }, []);

  // Restore position on component re-renders
  React.useEffect(() => {
    // Short delay after re-render to restore scroll position if not user-initiated
    const timeoutId = setTimeout(() => {
      if (!isUserInitiatedScroll()) {
        restoreScrollPosition();
      }
    }, 10);

    return () => clearTimeout(timeoutId);
  }, [children, isUserInitiatedScroll, restoreScrollPosition]);

  return (
    <ScrollAreaPrimitive.Root
      ref={ref}
      className={cn("relative overflow-hidden", className)}
      {...props}
    >
      <ScrollAreaPrimitive.Viewport
        ref={setViewportRef}
        className="h-full w-full rounded-[inherit]"
        tabIndex={0}
      >
        {children}
      </ScrollAreaPrimitive.Viewport>
      <ScrollBar />
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  );
});
StaticScrollArea.displayName = "StaticScrollArea";

const ScrollBar = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>
>(({ className, orientation = "vertical", ...props }, ref) => (
  <ScrollAreaPrimitive.ScrollAreaScrollbar
    ref={ref}
    orientation={orientation}
    className={cn(
      "flex touch-none select-none transition-colors",
      orientation === "vertical" &&
        "h-full w-2.5 border-l border-l-transparent p-[1px]",
      orientation === "horizontal" &&
        "h-2.5 flex-col border-t border-t-transparent p-[1px]",
      className
    )}
    {...props}
  >
    <ScrollAreaPrimitive.ScrollAreaThumb className="relative flex-1 rounded-full bg-gray-300 dark:bg-gray-700 transition-colors hover:bg-gray-400 dark:hover:bg-gray-600" />
  </ScrollAreaPrimitive.ScrollAreaScrollbar>
));
ScrollBar.displayName = ScrollAreaPrimitive.ScrollAreaScrollbar.displayName;

export { ScrollArea, StaticScrollArea, ScrollBar };
