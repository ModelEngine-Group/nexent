"use client";

import { useAuiState } from "@assistant-ui/react";
import type { SyntaxHighlighterProps } from "@assistant-ui/react-markdown";
import { Maximize2, Minus, Plus, RotateCcw, X } from "lucide-react";
import {
  type FC,
  type ReactNode,
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

export type MermaidDiagramProps = SyntaxHighlighterProps & {
  className?: string;
};

const MIN_SCALE = 0.5;
const MAX_SCALE = 4;

const MERMAID_CONFIG = {
  startOnLoad: false,
  securityLevel: "strict",
  theme: "base",
  fontFamily: "inherit",
  themeVariables: {
    primaryColor: "#EFF6FF",
    primaryTextColor: "#172554",
    primaryBorderColor: "#93C5FD",
    lineColor: "#2563EB",
    secondaryColor: "#E0F2FE",
    tertiaryColor: "#F8FAFC",
    background: "transparent",
    mainBkg: "#EFF6FF",
    secondBkg: "#F8FAFC",
    tertiaryBkg: "#F1F5F9",
    textColor: "#172554",
    labelTextColor: "#172554",
    nodeBorder: "#93C5FD",
    clusterBkg: "#F8FAFC",
    clusterBorder: "#CBD5E1",
    arrowheadColor: "#2563EB",
    edgeLabelBackground: "#FFFFFF",
  },
  flowchart: {
    useMaxWidth: true,
    htmlLabels: false,
    nodeSpacing: 25,
    rankSpacing: 30,
    diagramPadding: 8,
  },
} as const;

let mermaidId = 0;

function addSvgPadding(svg: string, padding = 12): string {
  return svg.replace(
    /viewBox="([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)"/,
    (_match, x, y, width, height) => {
      const values = [x, y, width, height].map(Number);
      if (values.some((value) => !Number.isFinite(value))) return _match;

      const [viewBoxX, viewBoxY, viewBoxWidth, viewBoxHeight] = values;
      return `viewBox="${viewBoxX - padding} ${viewBoxY - padding} ${viewBoxWidth + padding * 2} ${viewBoxHeight + padding * 2}"`;
    },
  );
}

type MermaidZoomProps = {
  svg: string;
  children: ReactNode;
};

function MermaidZoom({ svg, children }: MermaidZoomProps) {
  const [isMounted, setIsMounted] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const transformRef = useRef(transform);
  transformRef.current = transform;

  const zoomSvg = useMemo(
    () =>
      svg
        .replace(/id="([^"]+)"/g, 'id="$1-zoom"')
        .replace(/url\(#([^)]+)\)/g, "url(#$1-zoom)")
        .replace(/(href|xlink:href)="#([^"]+)"/g, '$1="#$2-zoom"'),
    [svg],
  );

  useEffect(() => {
    setIsMounted(true);
  }, []);

  const handleClose = useCallback(() => {
    setIsOpen(false);
    setTransform({ x: 0, y: 0, scale: 1 });
    triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        handleClose();
        return;
      }
      if (e.key !== "Tab") return;
      const focusables = overlayRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusables?.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, handleClose]);

  useEffect(() => {
    if (!isOpen) return;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = originalOverflow;
    };
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) closeRef.current?.focus();
  }, [isOpen]);

  const zoomBy = useCallback((factor: number, cx?: number, cy?: number) => {
    setTransform((t) => {
      const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, t.scale * factor));
      const ratio = scale / t.scale;
      if (cx === undefined || cy === undefined) {
        const viewport = viewportRef.current;
        cx = (viewport?.clientWidth ?? 0) / 2;
        cy = (viewport?.clientHeight ?? 0) / 2;
      }
      return {
        scale,
        x: cx - (cx - t.x) * ratio,
        y: cy - (cy - t.y) * ratio,
      };
    });
  }, []);

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      const viewport = viewportRef.current;
      if (!viewport) return;
      const rect = viewport.getBoundingClientRect();
      zoomBy(
        Math.exp(-e.deltaY * 0.0015),
        e.clientX - rect.left,
        e.clientY - rect.top,
      );
    },
    [zoomBy],
  );

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    const t = transformRef.current;
    drag.current = {
      startX: e.clientX,
      startY: e.clientY,
      originX: t.x,
      originY: t.y,
    };
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    setTransform((t) => ({
      ...t,
      x: d.originX + e.clientX - d.startX,
      y: d.originY + e.clientY - d.startY,
    }));
  }, []);

  const onPointerUp = useCallback(() => {
    drag.current = null;
  }, []);

  return (
    <div
      data-slot="mermaid-zoom-wrap"
      className="aui-mermaid-zoom-wrap group/mermaid relative"
    >
      {children}
      <button
        ref={triggerRef}
        type="button"
        data-slot="mermaid-zoom-trigger"
        aria-label="Expand diagram"
        onClick={() => setIsOpen(true)}
        className="aui-mermaid-zoom-trigger text-muted-foreground hover:text-foreground hover:border-muted-foreground/70 border-border bg-background absolute top-2 right-2 cursor-pointer rounded-md border p-1.5 opacity-0 transition group-hover/mermaid:opacity-100 focus-visible:opacity-100"
      >
        <Maximize2 className="size-3.5" />
      </button>
      {isMounted &&
        isOpen &&
        createPortal(
          <div
            ref={overlayRef}
            data-slot="mermaid-zoom-overlay"
            role="dialog"
            aria-modal="true"
            aria-label="Diagram"
            className="aui-mermaid-zoom-overlay fade-in animate-in bg-background fixed inset-0 z-50 duration-200"
          >
            <div
              ref={viewportRef}
              className="aui-mermaid-zoom-viewport h-full w-full cursor-grab touch-none overflow-hidden active:cursor-grabbing"
              onWheel={onWheel}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
            >
              <div
                data-slot="mermaid-zoom-content"
                className="aui-mermaid-zoom-content flex h-full w-full items-center justify-center [&_svg]:max-h-[80vh] [&_svg]:max-w-[90vw]"
                style={{
                  transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
                  transformOrigin: "0 0",
                }}
                dangerouslySetInnerHTML={{ __html: zoomSvg }}
              />
            </div>
            <div
              data-slot="mermaid-zoom-toolbar"
              className="aui-mermaid-zoom-toolbar border-border bg-background absolute top-4 right-4 flex items-center gap-1 rounded-lg border p-1 shadow-sm"
            >
              <button
                type="button"
                aria-label="Zoom in"
                onClick={() => zoomBy(1.25)}
                className="text-muted-foreground hover:text-foreground cursor-pointer rounded-sm p-1.5"
              >
                <Plus className="size-4" />
              </button>
              <button
                type="button"
                aria-label="Zoom out"
                onClick={() => zoomBy(0.8)}
                className="text-muted-foreground hover:text-foreground cursor-pointer rounded-sm p-1.5"
              >
                <Minus className="size-4" />
              </button>
              <button
                type="button"
                aria-label="Reset zoom"
                onClick={() => setTransform({ x: 0, y: 0, scale: 1 })}
                className="text-muted-foreground hover:text-foreground cursor-pointer rounded-sm p-1.5"
              >
                <RotateCcw className="size-4" />
              </button>
              <button
                ref={closeRef}
                type="button"
                aria-label="Close"
                onClick={handleClose}
                className="text-muted-foreground hover:text-foreground cursor-pointer rounded-sm p-1.5"
              >
                <X className="size-4" />
              </button>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

/**
 * Use it by passing to `componentsByLanguage` for mermaid in `markdown-text.tsx`.
 *
 * @example
 * const MarkdownTextImpl = () => {
 *   return (
 *     <MarkdownTextPrimitive
 *       remarkPlugins={[remarkGfm]}
 *       className="aui-md"
 *       components={defaultComponents}
 *       componentsByLanguage={{
 *         mermaid: {
 *           SyntaxHighlighter: MermaidDiagram
 *         },
 *       }}
 *     />
 *   );
 * };
 */
const MermaidDiagramImpl: FC<MermaidDiagramProps> = ({
  code,
  className,
  node: _node,
  components: _components,
  language: _language,
}) => {
  const isComplete = useAuiState(
    (s) => s.optional.part?.status.type !== "running",
  );
  const [result, setResult] = useState<
    { svg: string; error: null } | { svg: null; error: Error } | null
  >(null);

  useEffect(() => {
    if (!isComplete) {
      setResult(null);
      return;
    }

    let cancelled = false;
    const id = `newchat-mermaid-${++mermaidId}`;

    const render = async () => {
      try {
        const { default: mermaid } = await import("mermaid");
        mermaid.initialize(MERMAID_CONFIG);
        await mermaid.parse(code);

        const container = document.createElement("div");
        container.style.position = "absolute";
        container.style.visibility = "hidden";
        container.style.left = "-9999px";
        document.body.appendChild(container);

        try {
          const { svg } = await mermaid.render(id, code, container);
          if (!cancelled) setResult({ svg: addSvgPadding(svg), error: null });
        } finally {
          container.remove();
        }
      } catch (err) {
        if (!cancelled) {
          setResult({
            svg: null,
            error: err instanceof Error ? err : new Error(String(err)),
          });
        }
      }
    };

    void render();
    return () => {
      cancelled = true;
    };
  }, [isComplete, code]);

  if (!result) {
    return (
      <div
        data-slot="mermaid-skeleton"
        aria-label="Rendering diagram"
        className={cn(
          "aui-mermaid-skeleton bg-muted flex h-32 animate-pulse items-center justify-center gap-3 rounded-b-lg p-4",
          className,
        )}
      >
        <div className="bg-muted-foreground/20 h-8 w-20 rounded-md" />
        <div className="bg-muted-foreground/20 h-px w-10" />
        <div className="bg-muted-foreground/20 h-8 w-20 rounded-md" />
        <div className="bg-muted-foreground/20 h-px w-10" />
        <div className="bg-muted-foreground/20 h-8 w-20 rounded-md" />
      </div>
    );
  }

  if (result.error) {
    return (
      <div
        data-slot="mermaid-fallback"
        className={cn(
          "aui-mermaid-fallback bg-muted/75 rounded-b-lg",
          className,
        )}
      >
        <pre className="overflow-x-auto p-4 text-sm">{code.trim()}</pre>
        <p className="text-muted-foreground border-border border-t px-4 py-1.5 text-xs">
          diagram could not be rendered
        </p>
      </div>
    );
  }

  return (
    <MermaidZoom svg={result.svg}>
      <div
        data-slot="mermaid-diagram"
        className={cn(
          "aui-mermaid-diagram bg-muted rounded-b-lg px-2 pt-10 pb-2 [&_svg]:mx-auto",
          className,
        )}
        dangerouslySetInnerHTML={{ __html: result.svg }}
      />
    </MermaidZoom>
  );
};

const MermaidDiagram = memo(
  MermaidDiagramImpl,
) as unknown as FC<MermaidDiagramProps> & {
  Zoom: typeof MermaidZoom;
};

MermaidDiagram.displayName = "MermaidDiagram";
MermaidDiagram.Zoom = MermaidZoom;

export { MermaidDiagram, MermaidZoom };
