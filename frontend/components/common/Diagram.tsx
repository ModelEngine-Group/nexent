"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Code,
  Download,
  Eye,
  ZoomIn,
  ZoomOut,
  FileImage,
  FileText,
} from "lucide-react";
import { useTranslation } from "react-i18next";

// Download format type
type DownloadFormat = "svg" | "png";

// Diagram state interface
interface DiagramState {
  showCode: boolean;
  zoomLevel: number;
  panX: number;
  panY: number;
  downloadFormat: DownloadFormat;
}

// Global state manager for diagram view states
class DiagramStateManager {
  private static instance: DiagramStateManager;
  private states: Map<string, DiagramState> = new Map();
  private listeners: Map<string, Set<() => void>> = new Map();

  static getInstance(): DiagramStateManager {
    if (!DiagramStateManager.instance) {
      DiagramStateManager.instance = new DiagramStateManager();
    }
    return DiagramStateManager.instance;
  }

  getState(diagramId: string): DiagramState {
    return (
      this.states.get(diagramId) || {
        showCode: false,
        zoomLevel: 1,
        panX: 0,
        panY: 0,
        downloadFormat: "svg",
      }
    );
  }

  setShowCode(diagramId: string, showCode: boolean): void {
    const currentState = this.getState(diagramId);
    this.states.set(diagramId, { ...currentState, showCode });
    this.notifyListeners(diagramId);
  }

  setZoomLevel(diagramId: string, zoomLevel: number): void {
    const currentState = this.getState(diagramId);
    this.states.set(diagramId, {
      ...currentState,
      zoomLevel: Math.max(0.1, Math.min(5, zoomLevel)),
    });
    this.notifyListeners(diagramId);
  }

  setPan(diagramId: string, panX: number, panY: number): void {
    const currentState = this.getState(diagramId);
    this.states.set(diagramId, { ...currentState, panX, panY });
    this.notifyListeners(diagramId);
  }

  setDownloadFormat(diagramId: string, downloadFormat: DownloadFormat): void {
    const currentState = this.getState(diagramId);
    this.states.set(diagramId, { ...currentState, downloadFormat });
    this.notifyListeners(diagramId);
  }

  subscribe(diagramId: string, callback: () => void): () => void {
    if (!this.listeners.has(diagramId)) {
      this.listeners.set(diagramId, new Set());
    }
    this.listeners.get(diagramId)!.add(callback);

    return () => {
      this.listeners.get(diagramId)?.delete(callback);
    };
  }

  private notifyListeners(diagramId: string): void {
    this.listeners.get(diagramId)?.forEach((callback) => callback());
  }
}

interface DiagramProps {
  code: string;
  className?: string;
  maxHeight?: string | number;
  ariaLabel?: string;
  showToggle?: boolean; // Controls whether to show toggle buttons
}

type MermaidApi = {
  parse?: (code: string) => Promise<any> | any;
  render: (
    id: string,
    code: string,
    container?: Element
  ) => Promise<{ svg: string; bindFunctions?: () => void }>;
  initialize: (cfg: Record<string, unknown>) => void;
};

const memoryCache = new Map<string, string>();

function computeHash(input: string): string {
  let hash = 5381;
  for (let i = 0; i < input.length; i++) {
    hash = (hash * 33) ^ input.charCodeAt(i);
  }
  return (hash >>> 0).toString(16);
}

function DiagramComponent({
  code,
  className = "",
  maxHeight,
  ariaLabel,
  showToggle = true,
}: DiagramProps) {
  const { t } = useTranslation("common");
  const idRef = useRef<string>();
  const resultRef = useRef<{ dataUrl: string } | { error: string } | null>(
    null
  );
  const cacheKey = useMemo(() => computeHash(code), [code]);

  // Drag state for panning
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  // Format menu state
  const [showFormatMenu, setShowFormatMenu] = useState(false);

  // Close format menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (showFormatMenu && containerRef.current) {
        const target = event.target as Node;
        const isInsideContainer = containerRef.current.contains(target);
        const isFormatMenu = (target as Element)?.closest("[data-format-menu]");

        if (!isInsideContainer && !isFormatMenu) {
          setShowFormatMenu(false);
        }
      }
    };

    if (showFormatMenu) {
      // Use a small delay to avoid immediate closure
      const timeoutId = setTimeout(() => {
        document.addEventListener("mousedown", handleClickOutside);
      }, 10);

      return () => {
        clearTimeout(timeoutId);
        document.removeEventListener("mousedown", handleClickOutside);
      };
    }
  }, [showFormatMenu]);

  // Dynamic sizing based on diagram type
  const [isWideDiagram, setIsWideDiagram] = useState(false);

  // Fixed maxWidth to prevent flicker
  const getFixedMaxWidth = () => {
    return isWideDiagram ? "300px" : "400px";
  };

  // Generate stable diagram ID based on code content
  const diagramId = useMemo(() => `diagram-${cacheKey}`, [cacheKey]);

  // Use global state manager for persistent state
  const stateManager = useMemo(() => DiagramStateManager.getInstance(), []);
  const [diagramState, setDiagramState] = useState(() =>
    stateManager.getState(diagramId)
  );

  // Subscribe to state changes and sync with global state
  useEffect(() => {
    const unsubscribe = stateManager.subscribe(diagramId, () => {
      const newState = stateManager.getState(diagramId);
      setDiagramState(newState);
    });
    return unsubscribe;
  }, [stateManager, diagramId, diagramState]);

  // Update global state when local state changes
  const handleToggleShowCode = () => {
    const newState = !diagramState.showCode;
    stateManager.setShowCode(diagramId, newState);
  };

  const handleZoomIn = () => {
    // Limit maximum zoom to prevent excessive scaling
    const maxZoom = 3; // Maximum 3x zoom
    const newZoom = Math.min(diagramState.zoomLevel * 1.2, maxZoom);

    stateManager.setZoomLevel(diagramId, newZoom);
  };

  const handleZoomOut = () => {
    const newZoomLevel = diagramState.zoomLevel / 1.2;

    stateManager.setZoomLevel(diagramId, newZoomLevel);

    // Reset pan position when zoom level goes back to 1 or below
    if (newZoomLevel <= 1) {
      stateManager.setPan(diagramId, 0, 0);
    }
  };

  // Drag handling functions
  const handleMouseDown = (e: React.MouseEvent) => {
    if (diagramState.zoomLevel > 1) {
      setIsDragging(true);
      setDragStart({
        x: e.clientX - diagramState.panX,
        y: e.clientY - diagramState.panY,
      });
      e.preventDefault();
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging && diagramState.zoomLevel > 1) {
      const newPanX = e.clientX - dragStart.x;
      const newPanY = e.clientY - dragStart.y;
      stateManager.setPan(diagramId, newPanX, newPanY);
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleMouseLeave = () => {
    setIsDragging(false);
  };

  // Keyboard navigation support
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setIsDragging(false);
    }
  };

  // Convert SVG to PNG
  const convertSvgToPng = async (svgContent: string): Promise<string> => {
    return new Promise((resolve, reject) => {
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      const img = new Image();

      img.onload = () => {
        // Set canvas size to match SVG dimensions
        canvas.width = img.width;
        canvas.height = img.height;

        // Fill with white background
        if (ctx) {
          ctx.fillStyle = "#ffffff";
          ctx.fillRect(0, 0, canvas.width, canvas.height);

          // Draw the SVG
          ctx.drawImage(img, 0, 0);

          // Convert to PNG data URL
          const pngDataUrl = canvas.toDataURL("image/png");
          resolve(pngDataUrl);
        } else {
          reject(new Error("Failed to get canvas context"));
        }
      };

      img.onerror = () => {
        reject(new Error("Failed to load SVG"));
      };

      // Use the SVG content directly as data URL, not base64 encoded
      img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
        svgContent
      )}`;
    });
  };

  // Download function
  const handleDownloadClick = (e: React.MouseEvent) => {
    // Prevent event bubbling to avoid triggering handleClickOutside
    e.stopPropagation();
    e.preventDefault();

    setShowFormatMenu(!showFormatMenu);
  };

  const handleFormatSelect = async (format: DownloadFormat) => {
    setShowFormatMenu(false);

    // Use resultRef.current instead of result state for more reliable access
    const currentResult = resultRef.current;

    // Try currentResult first, then fallback to result state
    const dataSource = currentResult || result;

    if (dataSource && "dataUrl" in dataSource) {
      try {
        // Extract SVG content from data URL
        let svgContent: string;
        if (
          dataSource.dataUrl.startsWith("data:image/svg+xml;charset=utf-8,")
        ) {
          // Already encoded SVG content
          svgContent = decodeURIComponent(dataSource.dataUrl.split(",")[1]);
        } else if (
          dataSource.dataUrl.startsWith("data:image/svg+xml;base64,")
        ) {
          // Base64 encoded SVG content
          const base64Content = dataSource.dataUrl.split(",")[1];
          svgContent = atob(base64Content);
        } else {
          // Fallback: try to decode as URI component
          svgContent = decodeURIComponent(dataSource.dataUrl.split(",")[1]);
        }

        let blob: Blob;
        let filename: string;
        let mimeType: string;

        if (format === "png") {
          // Convert SVG to PNG
          const pngDataUrl = await convertSvgToPng(svgContent);
          const pngData = pngDataUrl.split(",")[1];
          blob = new Blob(
            [Uint8Array.from(atob(pngData), (c) => c.charCodeAt(0))],
            { type: "image/png" }
          );
          filename = `diagram-${cacheKey}.png`;
          mimeType = "image/png";
        } else {
          // Use SVG directly
          blob = new Blob([svgContent], { type: "image/svg+xml" });
          filename = `diagram-${cacheKey}.svg`;
          mimeType = "image/svg+xml";
        }
        // Create download link
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        // Clean up
        URL.revokeObjectURL(url);
      } catch (error) {
        // Fallback to SVG download
        try {
          let svgContent: string;
          if (
            dataSource.dataUrl.startsWith("data:image/svg+xml;charset=utf-8,")
          ) {
            svgContent = decodeURIComponent(dataSource.dataUrl.split(",")[1]);
          } else if (
            dataSource.dataUrl.startsWith("data:image/svg+xml;base64,")
          ) {
            const base64Content = dataSource.dataUrl.split(",")[1];
            svgContent = atob(base64Content);
          } else {
            svgContent = decodeURIComponent(dataSource.dataUrl.split(",")[1]);
          }

          const blob = new Blob([svgContent], { type: "image/svg+xml" });
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = `diagram-${cacheKey}.svg`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          URL.revokeObjectURL(url);
        } catch (fallbackError) {
          // Silent fallback failure
        }
      }
    }
  };

  // Generate stable ID only once
  if (!idRef.current) {
    idRef.current = `mmd-${Math.random().toString(36).slice(2)}`;
  }

  // Initialize result from cache if available
  if (!resultRef.current) {
    const cached = memoryCache.get(cacheKey);
    if (cached) {
      resultRef.current = { dataUrl: cached };
    }
  }

  const [result, setResult] = useState<
    { dataUrl: string } | { error: string } | null
  >(resultRef.current);

  useEffect(() => {
    let cancelled = false;

    // If we already have a result, don't re-render
    if (resultRef.current) {
      return;
    }

    const run = async () => {
      try {
        const mod = await import("mermaid");
        const mermaid: MermaidApi = mod.default as unknown as MermaidApi;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: "base",
          fontFamily: "inherit",
          // Optimize Gantt chart rendering
          themeVariables: {
            // Primary color - using project blue
            primaryColor: "#3b82f6",
            lineColor: "#6b7280",

            // Background colors - light theme
            background: "#ffffff",
            mainBkg: "#ffffff",
            secondBkg: "#f8fafc",
            tertiaryBkg: "#f1f5f9",

            // Text colors - gray theme
            textColor: "#6b7280",
            titleColor: "#6b7280",
            labelTextColor: "#6b7280",
            // Force set all possible text colors
            primaryTextColor: "#6b7280",
            sectionBkgColor: "#f8fafc",
            altSectionBkgColor: "#f1f5f9",
            secondaryColor: "#9ca3af",
            tertiaryColor: "#d1d5db",

            // Node colors
            nodeBkg: "#ffffff",
            nodeBorder: "#d1d5db",
            clusterBkg: "#f9fafb",
            clusterBorder: "#e5e7eb",

            // Arrows and connection lines
            arrowheadColor: "#6b7280",
            edgeLabelBackground: "#f8fafc",

            // Font sizes
            titleFontSize: "14px",

            // Force text color settings

            // Gantt chart colors
            section0: "#f0f9ff",
            section1: "#fef3c7",
            section2: "#fce7f3",
            section3: "#ecfdf5",
            section4: "#fef2f2",

            // Task colors
            task0: "#3b82f6",
            task1: "#f59e0b",
            task2: "#ec4899",
            task3: "#10b981",
            task4: "#ef4444",
            taskTextLightColor: "#ffffff",
            taskTextColor: "#6b7280",
            taskTextOutsideColor: "#6b7280",
            taskTextClickableColor: "#4b5563",

            // Active task colors
            activeTaskBkgColor: "#dbeafe",
            activeTaskBorderColor: "#3b82f6",
            gridLineColor: "#e5e7eb",

            // Timeline
            todayLineColor: "#ef4444",
          },
          flowchart: {
            useMaxWidth: true,
            htmlLabels: false,
            nodeSpacing: 25,
            rankSpacing: 30,
            diagramPadding: 8,
            curve: "basis",
          },
          sequence: {
            boxMargin: 8,
            diagramMarginX: 8,
            diagramMarginY: 8,
            actorFontSize: 12,
            noteFontSize: 10,
            messageFontSize: 11,
            messageAlign: "center",
            actorFontFamily: "inherit",
            messageFontFamily: "inherit",
            noteFontFamily: "inherit",
            actorFontWeight: "500",
            messageFontWeight: "400",
            noteFontWeight: "400",
          },
          gantt: {
            useMaxWidth: true,
            htmlLabels: false,
            fontSize: 14,
            topPadding: 30,
            leftPadding: 30,
            gridLineStartPadding: 20,
            sectionFontSize: 14,
            sectionFontWeight: "600",
            sectionFontFamily: "inherit",
            taskFontSize: 12,
            taskFontWeight: "500",
            taskFontFamily: "inherit",
            labelFontSize: 12,
            labelFontWeight: "500",
            labelFontFamily: "inherit",
            gridLineColor: "#e5e7eb",
            // Increase timeline label spacing
            axisFormat: "%m-%d",
            bottomPadding: 40,
            rightPadding: 20,
            // Optimize timeline display
            axisTextColor: "#6b7280",
            axisTextFontSize: 11,
            axisTextFontWeight: "500",
          },
          pie: {
            textPosition: 0.75,
            titleFontSize: 16,
            titleFontWeight: "600",
            titleFontFamily: "inherit",
            textFontSize: 12,
            textFontWeight: "400",
            textFontFamily: "inherit",
          },
          quadrantChart: {
            chartWidth: 400,
            chartHeight: 400,
            titleFontSize: 16,
            titleFontWeight: "600",
            titleFontFamily: "inherit",
            quadrant1TextFill: "#6b7280",
            quadrant2TextFill: "#6b7280",
            quadrant3TextFill: "#6b7280",
            quadrant4TextFill: "#6b7280",
            quadrant1Fill: "#f0f9ff",
            quadrant2Fill: "#fef3c7",
            quadrant3Fill: "#fce7f3",
            quadrant4Fill: "#ecfdf5",
            quadrantXAxisTextFill: "#9ca3af",
            quadrantYAxisTextFill: "#9ca3af",
            quadrantTitleFill: "#6b7280",
            quadrantInternalBorderStrokeFill: "#d1d5db",
            quadrantExternalBorderStrokeFill: "#9ca3af",
          },
          xyChart: {
            width: 400,
            height: 300,
            titleFontSize: 16,
            titleFontWeight: "600",
            titleFontFamily: "inherit",
            xAxisLabelFontSize: 12,
            xAxisLabelFontWeight: "400",
            xAxisLabelFontFamily: "inherit",
            yAxisLabelFontSize: 12,
            yAxisLabelFontWeight: "400",
            yAxisLabelFontFamily: "inherit",
            xAxisTitleFontSize: 14,
            xAxisTitleFontWeight: "500",
            xAxisTitleFontFamily: "inherit",
            yAxisTitleFontSize: 14,
            yAxisTitleFontWeight: "500",
            yAxisTitleFontFamily: "inherit",
            chartOrientation: "vertical",
            chartWidth: 400,
            chartHeight: 300,
            showValues: true,
            showValuesFontSize: 10,
            showValuesFontWeight: "400",
            showValuesFontFamily: "inherit",
          },
        });

        if (typeof mermaid.parse === "function") {
          await mermaid.parse(code);
        }

        // Offscreen container for stable layout measurement
        const container = document.createElement("div");
        container.style.position = "absolute";
        container.style.visibility = "hidden";
        container.style.left = "-9999px";
        container.style.top = "0";
        document.body.appendChild(container);

        try {
          const { svg } = await mermaid.render(idRef.current!, code, container);

          // Process SVG for rendering

          // Sanitize minimal: strip script and on* attributes
          const sanitized = svg
            .replace(/<script[\s\S]*?<\/script>/gi, "")
            .replace(/ on[a-z]+="[^"]*"/gi, "")
            .replace(/ on[a-z]+='[^']*'/gi, "");

          // Ensure preserveAspectRatio and vector-effect, but keep original dimensions
          const withSvgAttrs = sanitized.replace(/<svg(.*?)>/i, (_m, attrs) => {
            // Extract viewBox dimensions and set explicit width/height
            const viewBoxMatch = attrs.match(/viewBox="([^"]*)"/i);
            let processedAttrs = String(attrs);

            if (viewBoxMatch) {
              const viewBoxParts = viewBoxMatch[1].split(/\s+/);
              if (viewBoxParts.length >= 4) {
                const width = viewBoxParts[2];
                const height = viewBoxParts[3];

                // Replace percentage width with actual pixel width
                processedAttrs = processedAttrs.replace(
                  /width="[^"]*"/i,
                  `width="${width}"`
                );

                // Add height if missing
                if (!processedAttrs.match(/height="[^"]*"/i)) {
                  processedAttrs = processedAttrs.replace(
                    /<svg/i,
                    `<svg height="${height}"`
                  );
                }
              }
            }

            return `<svg${processedAttrs} preserveAspectRatio="xMidYMid meet">`;
          });

          const withVectorEffect = withSvgAttrs.replace(
            /<path /gi,
            '<path vector-effect="non-scaling-stroke" '
          );

          // Encode as data URL to avoid innerHTML
          const encoded = encodeURIComponent(withVectorEffect)
            .replace(/\(/g, "%28")
            .replace(/\)/g, "%29");
          const dataUrl = `data:image/svg+xml;charset=utf-8,${encoded}`;

          if (!cancelled) {
            memoryCache.set(cacheKey, dataUrl);
            resultRef.current = { dataUrl };
            setResult({ dataUrl });
          }
        } finally {
          if (document.body.contains(container)) {
            document.body.removeChild(container);
          }
        }
      } catch (err) {
        if (!cancelled) {
          resultRef.current = {
            error:
              err instanceof Error
                ? err.message
                : t("diagram.error.renderFailed"),
          };
          setResult({
            error:
              err instanceof Error
                ? err.message
                : t("diagram.error.renderFailed"),
          });
        }
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [cacheKey, code]);


  if (result && "error" in result) {
    return (
      <div className={`${className} mb-4`} style={{ maxHeight: maxHeight }}>
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
          <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap overflow-x-auto">
            <code>{code}</code>
          </pre>
        </div>
      </div>
    );
  }

  return (
    <div className={`${className} mb-4`} style={{ maxHeight: maxHeight }}>
      {/* Control buttons - only show if showToggle is true */}
      {showToggle && (
        <div className="flex justify-end gap-2 mb-2">
          {!diagramState.showCode && (
            <>
              <button
                onClick={handleZoomOut}
                className="inline-flex items-center justify-center w-8 h-8 text-xs font-medium text-gray-600 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 hover:text-gray-700 hover:border-gray-400 transition-all duration-200 shadow-sm"
                title={t("diagram.button.zoomOut")}
              >
                <ZoomOut size={14} />
              </button>
              <button
                onClick={handleZoomIn}
                className="inline-flex items-center justify-center w-8 h-8 text-xs font-medium text-gray-600 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 hover:text-gray-700 hover:border-gray-400 transition-all duration-200 shadow-sm"
                title={t("diagram.button.zoomIn")}
              >
                <ZoomIn size={14} />
              </button>
              <div className="relative">
                <button
                  onClick={handleDownloadClick}
                  className="inline-flex items-center justify-center w-8 h-8 text-xs font-medium text-gray-600 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 hover:text-gray-700 hover:border-gray-400 transition-all duration-200 shadow-sm"
                  title={t("diagram.button.download")}
                >
                  <Download size={14} />
                </button>
                {showFormatMenu && (
                  <div
                    data-format-menu="true"
                    className="absolute right-0 top-full mt-1 w-36 bg-white border border-gray-200 rounded-md shadow-lg z-50"
                    onClick={(e) => {
                      e.stopPropagation();
                    }}
                  >
                    <div className="py-1">
                      <button
                        onClick={() => {
                          handleFormatSelect("svg");
                        }}
                        className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-gray-50 text-gray-700"
                      >
                        <FileText size={14} />
                        {t("diagram.format.svg")}
                      </button>
                      <button
                        onClick={() => {
                          handleFormatSelect("png");
                        }}
                        className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-gray-50 text-gray-700"
                      >
                        <FileImage size={14} />
                        {t("diagram.format.png")}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
          <button
            onClick={handleToggleShowCode}
            className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 hover:text-gray-700 hover:border-gray-400 transition-all duration-200 shadow-sm"
            title={
              diagramState.showCode
                ? t("diagram.button.showDiagram")
                : t("diagram.button.showCode")
            }
          >
            {diagramState.showCode ? (
              <>
                <Eye size={14} />
                {t("diagram.button.showDiagram")}
              </>
            ) : (
              <>
                <Code size={14} />
                {t("diagram.button.showCode")}
              </>
            )}
          </button>
        </div>
      )}

      {/* Content area */}
      {diagramState.showCode ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
          <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap overflow-x-auto">
            <code>{code}</code>
          </pre>
        </div>
      ) : (
        <>
          {!result || !("dataUrl" in result) ? (
            <div className="mermaid-loading flex justify-center items-center py-8">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400" />
            </div>
          ) : (
            <div
              ref={containerRef}
              className="w-full overflow-hidden"
              style={{
                maxHeight: maxHeight || "auto",
                height: "auto",
                minHeight:
                  diagramState.zoomLevel !== 1
                    ? `${
                        (isWideDiagram ? 200 : 400) *
                        Math.max(diagramState.zoomLevel, 0.5)
                      }px`
                    : "auto",
                cursor:
                  diagramState.zoomLevel > 1
                    ? isDragging
                      ? "grabbing"
                      : "grab"
                    : "default",
              }}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseLeave}
              onKeyDown={handleKeyDown}
              tabIndex={diagramState.zoomLevel > 1 ? 0 : -1}
            >
              <img
                src={result.dataUrl}
                alt={ariaLabel || "diagram"}
                className="h-auto block mx-auto"
                style={{
                  // Simplified maxWidth logic - no dynamic adjustment based on zoom
                  maxWidth: getFixedMaxWidth(),
                  height: "auto",
                  display: "block",
                  // Optimized transform - separate scale and translate for better performance
                  transform: `translate(${diagramState.panX}px, ${diagramState.panY}px) scale(${diagramState.zoomLevel})`,
                  transformOrigin: "center",
                  // Add smooth transition for better UX
                  transition: "transform 0.2s ease-out",
                  // Remove conflicting minWidth
                  pointerEvents: "none", // Prevent image from interfering with drag events
                }}
                onLoad={(e) => {
                  const img = e.target as HTMLImageElement;
                  const aspectRatio = img.naturalWidth / img.naturalHeight;
                  const isWide = aspectRatio > 1.5; // Aspect ratio > 1.5 is considered a wide chart

                  setIsWideDiagram(isWide);
                }}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

// Memoize the component to prevent unnecessary re-renders
export const Diagram = React.memo(DiagramComponent);
