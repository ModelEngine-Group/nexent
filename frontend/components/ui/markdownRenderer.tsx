"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeRaw from "rehype-raw";
import rehypeKatex from "rehype-katex";
// @ts-ignore
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
// @ts-ignore
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import { visit } from "unist-util-visit";
import { SearchResult } from "@/types/chat";
import { resolveS3UrlToDataUrl } from "@/services/storageService";
import { Tooltip, TooltipProvider } from "@/components/ui/tooltip";
import { CopyButton } from "@/components/ui/copyButton";
import { Diagram } from "@/components/ui/Diagram";

interface MarkdownRendererProps {
  content: string;
  className?: string;
  searchResults?: SearchResult[];
  showDiagramToggle?: boolean;
  onCitationHover?: () => void;
  enableMultimodal?: boolean;
  /**
   * When true, resolve s3:// media URLs in markdown into data URLs (base64)
   * so that images can still be displayed after page refresh or when
   * the original S3 URL is not directly accessible by the browser.
   */
  resolveS3Media?: boolean;
}

// Simple in-memory cache to avoid refetching the same S3 object multiple times
const s3MediaCache = new Map<string, string>();
const mediaObjectUrlCache = new Map<string, string>();
const mediaObjectUrlPromiseCache = new Map<string, Promise<string | null>>();
const S3_MEDIA_SESSION_PREFIX = "s3-media-cache:";

const isBrowserEnvironment = typeof window !== "undefined";

const getSessionCachedValue = (key: string): string | null => {
  if (!isBrowserEnvironment) {
    return null;
  }
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
};

const getCachedMediaSrc = (src: string): string | null => {
  const cached = s3MediaCache.get(src);
  if (cached) {
    return cached;
  }
  const sessionValue = getSessionCachedValue(src);
  if (sessionValue) {
    s3MediaCache.set(src, sessionValue);
    return sessionValue;
  }
  return null;
};

const setCachedMediaSrc = (src: string, value: string) => {
  s3MediaCache.set(src, value);
  if (!isBrowserEnvironment) {
    return;
  }
  try {
    window.sessionStorage.setItem(`${S3_MEDIA_SESSION_PREFIX}${src}`, value);
  } catch {
    // Ignore storage quota errors silently.
  }
};

const setCachedObjectUrl = (src: string, objectUrl: string | null) => {
  if (!objectUrl) {
    return;
  }
  const existing = mediaObjectUrlCache.get(src);
  if (existing && existing !== objectUrl) {
    URL.revokeObjectURL(existing);
  }
  mediaObjectUrlCache.set(src, objectUrl);
};

const resolveMediaToObjectUrl = async (
  src: string,
  { resolveS3 }: { resolveS3: boolean }
): Promise<string | null> => {
  try {
    if (src.startsWith("blob:")) {
      return src;
    }

    if (src.startsWith("s3://")) {
      if (!resolveS3) {
        return null;
      }
      const dataUrl = await resolveS3UrlToDataUrl(src);
      if (!dataUrl) {
        return null;
      }
      const response = await fetch(dataUrl);
      if (!response.ok) {
        return null;
      }
      const blob = await response.blob();
      return URL.createObjectURL(blob);
    }

    if (
      src.startsWith("http://") ||
      src.startsWith("https://") ||
      src.startsWith("/api/") ||
      src.startsWith("/nexent/") ||
      src.startsWith("/attachments/") ||
      src.startsWith("/")
    ) {
      const response = await fetch(src);
      if (!response.ok) {
        return null;
      }
      const blob = await response.blob();
      return URL.createObjectURL(blob);
    }

    if (src.startsWith("data:")) {
      const response = await fetch(src);
      if (!response.ok) {
        return null;
      }
      const blob = await response.blob();
      return URL.createObjectURL(blob);
    }

    return null;
  } catch {
    return null;
  }
};

const usePrefetchedMediaSource = (
  src?: string,
  options?: { enable?: boolean; resolveS3?: boolean }
) => {
  const shouldPrefetch =
    Boolean(
      options?.enable &&
        src &&
        typeof src === "string" &&
        !src.startsWith("blob:") &&
        (src.startsWith("s3://") ||
          src.startsWith("http://") ||
          src.startsWith("https://") ||
          src.startsWith("/"))
    ) || false;

  const [resolvedSrc, setResolvedSrc] = React.useState<string | null>(() => {
    if (!src || typeof src !== "string") {
      return null;
    }
    if (!shouldPrefetch) {
      return src;
    }
    return mediaObjectUrlCache.get(src) ?? null;
  });

  React.useEffect(() => {
    if (!src || typeof src !== "string") {
      setResolvedSrc(null);
      return;
    }

    if (!shouldPrefetch) {
      setResolvedSrc(src);
      return;
    }

    const cached = mediaObjectUrlCache.get(src);
    if (cached) {
      setResolvedSrc(cached);
      return;
    }

    let cancelled = false;

    const promise =
      mediaObjectUrlPromiseCache.get(src) ??
      resolveMediaToObjectUrl(src, {
        resolveS3: options?.resolveS3 ?? true,
      });

    mediaObjectUrlPromiseCache.set(src, promise);

    promise
      .then((objectUrl) => {
        if (cancelled) {
          return;
        }
        if (!objectUrl) {
          setResolvedSrc(null);
          return;
        }
        setCachedObjectUrl(src, objectUrl);
        setResolvedSrc(objectUrl);
      })
      .catch(() => {
        if (!cancelled) {
          setResolvedSrc(null);
        }
      })
      .finally(() => {
        mediaObjectUrlPromiseCache.delete(src);
      });

    return () => {
      cancelled = true;
    };
  }, [options?.resolveS3, shouldPrefetch, src]);

  return resolvedSrc;
};

const useResolvedS3Media = (src?: string, shouldResolve?: boolean) => {
  const cachedInitial =
    typeof src === "string" && src.startsWith("s3://")
      ? getCachedMediaSrc(src)
      : null;
  const initialValue =
    typeof src === "string"
      ? !shouldResolve || !src.startsWith("s3://")
        ? src
        : cachedInitial
      : null;
  const [resolvedSrc, setResolvedSrc] = React.useState<string | null>(
    initialValue
  );

  React.useEffect(() => {
    if (!src || typeof src !== "string") {
      setResolvedSrc(null);
      return;
    }

    if (!shouldResolve || !src.startsWith("s3://")) {
      setResolvedSrc(src);
      return;
    }

    const cached = getCachedMediaSrc(src);
    if (cached) {
      setResolvedSrc(cached);
      return;
    }

    let cancelled = false;

    resolveS3UrlToDataUrl(src)
      .then((dataUrl) => {
        if (cancelled) {
          return;
        }
        if (dataUrl) {
          setCachedMediaSrc(src, dataUrl);
          setResolvedSrc(dataUrl);
        } else {
          setResolvedSrc(null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setResolvedSrc(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [src, shouldResolve]);

  return resolvedSrc;
};

const VIDEO_EXTENSIONS = [".mp4", ".webm", ".ogg", ".mov", ".m4v"];

const extractExtension = (value: string): string => {
  const normalized = value.split("?")[0].split("#")[0];
  const match = normalized.toLowerCase().match(/\.[a-z0-9]+$/);
  return match?.[0] ?? "";
};

const isVideoUrl = (url?: string): boolean => {
  if (!url) {
    return false;
  }

  const trimmed = url.trim();
  if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
    return false;
  }

  const extension = extractExtension(trimmed);
  return VIDEO_EXTENSIONS.includes(extension);
};

// extract block level elements from <p>
const rehypeUnwrapMedia = () => {
  return (tree: any) => {
    visit(tree, "element", (node, index, parent) => {
      // find <p> tags containing video or figure
      if (node.tagName === "p" && node.children) {
        const mediaChildIndex = node.children.findIndex(
          (child: any) =>
            child.tagName === "video" || child.tagName === "figure"
        );

        if (mediaChildIndex !== -1) {
          // extract media elements (video/figure)
          const mediaChild = node.children.splice(mediaChildIndex, 1)[0];

          // if <p> has other content after extraction, keep <p>; otherwise remove empty <p>
          if (node.children.length === 0) {
            // replace original <p> node with media element
            if (parent && index !== null) {
              parent.children[index as number] = {
                tagName: "div",
                properties: { className: "markdown-media-container" },
                children: [mediaChild],
              };
            }
          } else {
            // if <p> has other content after extraction, keep <p>; otherwise remove empty <p>
            if (parent && index !== null) {
              parent.children.splice((index as number) + 1, 0, {
                tagName: "div",
                properties: { className: "markdown-media-container" },
                children: [mediaChild],
              });
            }
          }
        }
      }
    });
  };
};

// Get background color for different tool signs
const getBackgroundColor = (toolSign: string) => {
  switch (toolSign) {
    case "a":
      return "#E3F2FD"; // Light blue
    case "b":
      return "#E8F5E9"; // Light green
    case "c":
      return "#FFF3E0"; // Light orange
    case "d":
      return "#F3E5F5"; // Light purple
    case "e":
      return "#FFEBEE"; // Light red
    default:
      return "#E5E5E5"; // Default light gray
  }
};

// Replace the original LinkIcon component
const CitationBadge = ({
  toolSign,
  citeIndex,
}: {
  toolSign: string;
  citeIndex: number;
}) => (
  <span
    className="ds-markdown-cite"
    style={{
      verticalAlign: "middle",
      fontVariant: "tabular-nums",
      boxSizing: "border-box",
      color: "#404040",
      cursor: "pointer",
      background: getBackgroundColor(toolSign),
      borderRadius: "9px",
      flexShrink: 0,
      justifyContent: "center",
      alignItems: "center",
      height: "18px",
      marginLeft: "4px",
      padding: "0 6px",
      fontSize: "12px",
      fontWeight: 400,
      display: "inline-flex",
      position: "relative",
      top: "-2px",
    }}
  >
    {citeIndex}
  </span>
);

// Modified HoverableText component
const HoverableText = ({
  text,
  searchResults,
  onCitationHover,
}: {
  text: string;
  searchResults?: SearchResult[];
  onCitationHover?: () => void;
}) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLSpanElement>(null);
  const tooltipRef = React.useRef<HTMLDivElement>(null);
  const mousePositionRef = React.useRef({ x: 0, y: 0 });

  // Function to handle multiple consecutive line breaks
  const handleConsecutiveNewlines = (text: string) => {
    if (!text) return text;
    return (
      text
        // First, standardize all types of line breaks to \n
        .replace(/\r\n/g, "\n") // Windows line breaks
        .replace(/\r/g, "\n") // Old Mac line breaks
        // Handle consecutive line breaks and whitespace
        .replace(/[\n\s]*\n[\n\s]*/g, "\n") // Process whitespace around line breaks
        .replace(/^\s+|\s+$/g, "")
    ); // Remove leading and trailing whitespace
  };

  // Find corresponding search result
  const toolSign = text.charAt(0);
  const citeIndex = parseInt(text.slice(1));
  const matchedResult = searchResults?.find(
    (result) => result.tool_sign === toolSign && result.cite_index === citeIndex
  );

  // Handle mouse events
  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let timeoutId: NodeJS.Timeout | null = null;
    let closeTimeoutId: NodeJS.Timeout | null = null;

    // Function to update mouse position
    const updateMousePosition = (e: MouseEvent) => {
      mousePositionRef.current = { x: e.clientX, y: e.clientY };
    };

    const handleMouseEnter = () => {
      // Clear any existing close timer
      if (closeTimeoutId) {
        clearTimeout(closeTimeoutId);
        closeTimeoutId = null;
      }

      if (timeoutId) {
        clearTimeout(timeoutId);
      }

      // Clear completed conversation indicator when hovering over citation
      if (onCitationHover) {
        onCitationHover();
      }

      // Delay before showing tooltip to avoid quick hover triggers
      timeoutId = setTimeout(() => {
        setIsOpen(true);
      }, 50);
    };

    const handleMouseLeave = () => {
      // Clear open timer
      if (timeoutId) {
        clearTimeout(timeoutId);
        timeoutId = null;
      }

      // Delay closing tooltip so user can move to tooltip content
      closeTimeoutId = setTimeout(() => {
        checkShouldClose();
      }, 100);
    };

    // Function to check if tooltip should be closed
    const checkShouldClose = () => {
      const linkElement = containerRef.current;
      const { x: mouseX, y: mouseY } = mousePositionRef.current;

      // Find any visible tooltip popups (antd uses role="tooltip")
      const tooltipEls = Array.from(document.querySelectorAll('[role="tooltip"]')) as HTMLElement[];
      const isMouseOverTooltip = tooltipEls.some((el) => {
        const rect = el.getBoundingClientRect();
        return mouseX >= rect.left && mouseX <= rect.right && mouseY >= rect.top && mouseY <= rect.bottom;
      });

      if (!linkElement && !isMouseOverTooltip) {
        setIsOpen(false);
        return;
      }

      const linkRect = linkElement?.getBoundingClientRect();

      const isMouseOverLink = !!linkRect && mouseX >= linkRect.left && mouseX <= linkRect.right && mouseY >= linkRect.top && mouseY <= linkRect.bottom;

      // Close tooltip if mouse is neither over tooltip nor link icon
      if (!isMouseOverTooltip && !isMouseOverLink) {
        setIsOpen(false);
      }
    };

    // Add global mouse move event listener to handle movement anywhere
    const handleGlobalMouseMove = (e: MouseEvent) => {
      // Update mouse position
      updateMousePosition(e);

      if (!isOpen) return;

      // Use debounce logic to avoid frequent calculations
      if (closeTimeoutId) {
        clearTimeout(closeTimeoutId);
      }

      closeTimeoutId = setTimeout(() => {
        checkShouldClose();
      }, 100);
    };

    // Add event listeners
    document.addEventListener("mousemove", handleGlobalMouseMove);
    container.addEventListener("mouseenter", handleMouseEnter);
    container.addEventListener("mouseleave", handleMouseLeave);

    return () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      if (closeTimeoutId) {
        clearTimeout(closeTimeoutId);
      }
      document.removeEventListener("mousemove", handleGlobalMouseMove);
      container.removeEventListener("mouseenter", handleMouseEnter);
      container.removeEventListener("mouseleave", handleMouseLeave);
    };
  }, [isOpen, onCitationHover]);

  return (
    <TooltipProvider>
      <Tooltip
        styles={{
          container: { padding: 0, background: "transparent", boxShadow: "none" },
        }}
        title={
          <div
            className="z-[9999] bg-white px-3 py-2 text-sm border border-gray-200 rounded-md shadow-md max-w-xl overflow-hidden"
            style={
              {
                "--scrollbar-width": "8px",
                "--scrollbar-height": "8px",
                "--scrollbar-track-bg": "transparent",
                "--scrollbar-thumb-bg": "rgb(209, 213, 219)",
                "--scrollbar-thumb-hover-bg": "rgb(156, 163, 175)",
                "--scrollbar-thumb-radius": "9999px",
                boxSizing: "border-box",
                /* allow larger tooltip but constrain to viewport */
                maxWidth: "min(720px, 50vw)",
                width: "min(720px, 50vw)",
              } as React.CSSProperties
            }
          >
            <div
              ref={tooltipRef}
              className="whitespace-pre-wrap overflow-y-auto"
              style={{
                maxHeight: 240,
                minWidth: 360,
                width: "100%",
                maxWidth: "min(680px, 95vw)",
                scrollbarWidth: "thin",
                scrollbarColor:
                  "var(--scrollbar-thumb-bg) var(--scrollbar-track-bg)",
                wordBreak: "break-word",
                overflowWrap: "break-word",
                overflowX: "auto",
              }}
            >
              <style jsx>{`
                div::-webkit-scrollbar {
                  width: var(--scrollbar-width);
                  height: var(--scrollbar-height);
                }
                div::-webkit-scrollbar-track {
                  background: var(--scrollbar-track-bg);
                }
                div::-webkit-scrollbar-thumb {
                  background: var(--scrollbar-thumb-bg);
                  border-radius: var(--scrollbar-thumb-radius);
                }
                div::-webkit-scrollbar-thumb:hover {
                  background: var(--scrollbar-thumb-hover-bg);
                }
                @media (prefers-color-scheme: dark) {
                  div::-webkit-scrollbar-thumb {
                    background: rgb(55, 65, 81);
                  }
                  div::-webkit-scrollbar-thumb:hover {
                    background: rgb(75, 85, 99);
                  }
                }
              `}</style>
              {matchedResult ? (
                <>
                  {matchedResult.url &&
                  matchedResult.source_type !== "file" &&
                  !matchedResult.filename ? (
                    <a
                      href={matchedResult.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium mb-1 text-blue-600 hover:underline block"
                      style={{ wordBreak: "break-all" }}
                    >
                      {handleConsecutiveNewlines(matchedResult.title)}
                    </a>
                  ) : (
                    <p className="font-medium mb-1">
                      {handleConsecutiveNewlines(matchedResult.title)}
                    </p>
                  )}
                  <p className="text-gray-600">
                    {handleConsecutiveNewlines(matchedResult.text)}
                  </p>
                </>
              ) : null}
            </div>
          </div>
        }
        open={isOpen}
        placement="top"
      >
        <span
          ref={containerRef}
          className="inline-flex items-center relative"
          style={{ zIndex: isOpen ? 1000 : "auto" }}
        >
          <span className="inline-flex items-center cursor-pointer transition-colors">
            <CitationBadge toolSign={toolSign} citeIndex={citeIndex} />
          </span>
        </span>
      </Tooltip>
    </TooltipProvider>
  );
};

/**
 * Convert LaTeX delimiters to markdown math delimiters
 *
 * Converts:
 * - \( ... \) to $ ... $
 * - \[ ... \] to $$ ... $$
 */
const convertLatexDelimiters = (content: string): string => {
  // Quick check: only process if LaTeX delimiters are present
  if (!content.includes('\\(') && !content.includes('\\[')) {
    return content;
  }

  return (
    content
      // Convert \( ... \) to $ ... $ (inline math)
      .replace(/\\\(([\s\S]*?)\\\)/g, (_match, inner) => `$${inner}$`)
      // Convert \[ ... \] to $$ ... $$ (display math)
      .replace(/\\\[([\s\S]*?)\\\]/g, (_match, inner) => `$$${inner}$$\n`)
  );
};

// Video component with error handling - defined outside to prevent re-creation on each render
interface VideoWithErrorHandlingProps {
  src: string;
  alt?: string | null;
  props?: React.VideoHTMLAttributes<HTMLVideoElement>;
}

const VideoWithErrorHandling: React.FC<VideoWithErrorHandlingProps> = React.memo(({ src, alt, props = {} }) => {
  const { t } = useTranslation("common");
  const [hasError, setHasError] = React.useState(false);

  if (hasError) {
    return (
      <div className="markdown-media-error">
        <div className="markdown-media-error-message">
          {t("chatStreamMessage.videoLinkUnavailable", {
            defaultValue: "This video link is unavailable",
          })}
        </div>
        {alt && (
          <div className="markdown-media-error-caption">{alt}</div>
        )}
      </div>
    );
  }

  return (
    <figure className="markdown-video-wrapper">
      <video
        className="markdown-video"
        controls
        preload="metadata"
        playsInline
        src={src}
        onError={() => setHasError(true)}
        {...props}
      >
        {t("chatStreamMessage.videoNotSupported", {
          defaultValue: "Sorry, your browser does not support embedded videos.",
        })}
      </video>
      {alt ? (
        <figcaption className="markdown-video-caption">{alt}</figcaption>
      ) : null}
    </figure>
  );
}, (prevProps, nextProps) => {
  // Custom comparison function to prevent unnecessary re-renders
  // Only compare src and alt, props object reference may change but content is the same
  return prevProps.src === nextProps.src &&
         prevProps.alt === nextProps.alt;
});

VideoWithErrorHandling.displayName = "VideoWithErrorHandling";

// Image component with error handling - defined outside to prevent re-creation on each render
interface ImageWithErrorHandlingProps {
  src: string;
  alt?: string | null;
}

const ImageWithErrorHandling: React.FC<ImageWithErrorHandlingProps> = React.memo(({ src, alt }) => {
  const { t } = useTranslation("common");
  const [hasError, setHasError] = React.useState(false);

  if (hasError) {
    return (
      <div className="markdown-media-error">
        <div className="markdown-media-error-message">
          {t("chatStreamMessage.imageLinkUnavailable", {
            defaultValue: "This image link is unavailable",
          })}
        </div>
        {alt && (
          <div className="markdown-media-error-caption">{alt}</div>
        )}
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt ?? undefined}
      className="markdown-img"
      onError={() => setHasError(true)}
    />
  );
}, (prevProps, nextProps) => {
  // Custom comparison function to prevent unnecessary re-renders
  return prevProps.src === nextProps.src &&
         prevProps.alt === nextProps.alt;
});

ImageWithErrorHandling.displayName = "ImageWithErrorHandling";

/**
 * Render a code block with syntax highlighting, language label, and copy button
 * This is exported for use in other components that need to render code blocks directly
 */
export const CodeBlock: React.FC<{
  codeContent: string;
  language?: string;
}> = ({ codeContent, language = "python" }) => {
  const { t } = useTranslation("common");

  const customStyle = {
    ...oneLight,
    'pre[class*="language-"]': {
      ...oneLight['pre[class*="language-"]'],
      background: "#f8f8f8",
      borderRadius: "0",
      padding: "12px 16px",
      margin: "0",
      fontSize: "0.875rem",
      lineHeight: "1.5",
      whiteSpace: "pre-wrap",
      wordWrap: "break-word",
      wordBreak: "break-word",
      overflowWrap: "break-word",
      overflow: "auto",
      width: "100%",
      boxSizing: "border-box",
      display: "block",
      borderTop: "none",
    },
    'code[class*="language-"]': {
      ...oneLight['code[class*="language-"]'],
      background: "#f8f8f8",
      color: "#333333",
      fontSize: "0.875rem",
      lineHeight: "1.5",
      whiteSpace: "pre-wrap",
      wordWrap: "break-word",
      wordBreak: "break-word",
      overflowWrap: "break-word",
      width: "100%",
      padding: "0",
      display: "block",
    },
  };

  const cleanedContent = codeContent.replace(/^\n+|\n+$/g, "");

  return (
    <div className="code-block-container group">
      <div className="code-block-header">
        <span className="code-language-label" data-language={language}>
          {language}
        </span>
        <CopyButton
          content={cleanedContent}
          variant="code-block"
          className="header-copy-button"
          tooltipText={{
            copy: t("chatStreamMessage.copyContent"),
            copied: t("chatStreamMessage.copied"),
          }}
        />
      </div>
      <div className="code-block-content">
        <SyntaxHighlighter style={customStyle} language={language} PreTag="div">
          {cleanedContent}
        </SyntaxHighlighter>
      </div>
    </div>
  );
};

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className,
  searchResults = [],
  showDiagramToggle = true,
  onCitationHover,
  enableMultimodal = true,
  resolveS3Media = false,
}) => {
  const { t } = useTranslation("common");

  // Convert LaTeX delimiters to markdown math delimiters
  const processedContent = convertLatexDelimiters(content);

  const renderCodeFallback = (text: string, key?: React.Key) => (
    <code
      key={key}
      className="markdown-code block whitespace-pre-wrap break-words text-xs"
      style={{ fontFamily: "var(--font-mono, monospace)" }}
    >
      {text}
    </code>
  );

  const buildMediaFallbackText = (src?: string | null, alt?: string | null) => {
    if (alt) {
      return `${t("chatStreamMessage.imageTextFallbackTitle", {
        defaultValue: "Media (text view)",
      })}: ${alt}${src ? ` - ${src}` : ""}`;
    }
    return (
      src ??
      t("chatStreamMessage.imageTextFallbackTitle", {
        defaultValue: "Media (text view)",
      })
    );
  };

  const renderMediaFallback = (src?: string | null, alt?: string | null) =>
    renderCodeFallback(buildMediaFallbackText(src, alt));

  const renderVideoElement = ({
    src,
    alt,
    props = {},
  }: {
    src?: string | null;
    alt?: string | null;
    props?: React.VideoHTMLAttributes<HTMLVideoElement>;
  }) => {
    if (!src) {
      return null;
    }

    if (!enableMultimodal) {
      return renderMediaFallback(src, alt);
    }

    return <VideoWithErrorHandling key={src} src={src} alt={alt} props={props} />;
  };

  const ImageResolver: React.FC<{ src?: string; alt?: string | null }> = ({
    src,
    alt,
  }) => {
    const resolvedSrc = useResolvedS3Media(
      typeof src === "string" ? src : undefined,
      resolveS3Media
    );

    if (!enableMultimodal) {
      return renderMediaFallback(src, alt);
    }

    if (!resolvedSrc) {
      return renderMediaFallback(src, alt);
    }

    if (isVideoUrl(resolvedSrc)) {
      return renderVideoElement({ src: resolvedSrc, alt });
    }

    return <ImageWithErrorHandling key={resolvedSrc} src={resolvedSrc} alt={alt} />;
  };

  // Modified processText function logic
  const processText = (text: string) => {
    if (typeof text !== "string") return text;

    const parts = text.split(/(\[\[[^\]]+\]\]|:mermaid\[[^\]]+\])/g);
    return (
      <>
        {parts.map((part, index) => {
          const match = part.match(/^\[\[([^\]]+)\]\]$/);
          if (match) {
            const innerText = match[1];

            const toolSign = innerText.charAt(0);
            const citeIndex = parseInt(innerText.slice(1));
            const hasMatch = searchResults?.some(
              (result) =>
                result.tool_sign === toolSign && result.cite_index === citeIndex
            );

            // Only show citation icon when matching search result is found
            if (hasMatch) {
              return (
                <HoverableText
                  key={index}
                  text={innerText}
                  searchResults={searchResults}
                  onCitationHover={onCitationHover}
                />
              );
            } else {
              // Return empty string if no matching result found (display nothing)
              return "";
            }
          }
          // Inline Mermaid using :mermaid[graph LR; A-->B] - removed inline support
          const mmd = part.match(/^:mermaid\[([^\]]+)\]$/);
          if (mmd) {
            const code = mmd[1];
            if (!enableMultimodal) {
              return renderCodeFallback(code, `mmd-placeholder-${index}`);
            }
            return <Diagram key={`mmd-${index}`} code={code} className="my-4" />;
          }
          // Handle line breaks in text content
          if (part.includes('\n')) {
            return part.split('\n').map((line, lineIndex) => (
              <React.Fragment key={`${index}-${lineIndex}`}>
                {line}
                {lineIndex < part.split('\n').length - 1 && <br />}
              </React.Fragment>
            ));
          }
          return part;
        })}
      </>
    );
  };

  // Create wrapper component to handle different types of child elements
  const TextWrapper = ({ children }: { children: any }) => {
    if (typeof children === "string") {
      return processText(children);
    }
    if (Array.isArray(children)) {
      return (
        <>
          {children.map((child, index) => {
            if (typeof child === "string") {
              return (
                <React.Fragment key={index}>
                  {processText(child)}
                </React.Fragment>
              );
            }
            return child;
          })}
        </>
      );
    }
    return children;
  };

  class MarkdownErrorBoundary extends React.Component<
    { children: React.ReactNode; rawContent: string },
    { hasError: boolean }
  > {
    constructor(props: { children: React.ReactNode; rawContent: string }) {
      super(props);
      this.state = { hasError: false };
    }
    static getDerivedStateFromError() {
      return { hasError: true };
    }
    componentDidCatch(error: unknown) {}
    render() {
      if (this.state.hasError) {
        return (
          <div className="markdown-body">
            <pre className="whitespace-pre-wrap break-words text-sm">
              {this.props.rawContent}
            </pre>
          </div>
        );
      }
      return this.props.children as React.ReactElement;
    }
  }

  return (
    <>
      <div className={`markdown-body ${className || ""}`}>
        <MarkdownErrorBoundary rawContent={processedContent}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath] as any}
            rehypePlugins={
              [
                rehypeUnwrapMedia,
                [
                  rehypeKatex,
                  {
                    throwOnError: false,
                    strict: false,
                    trust: true,
                  },
                ],
                rehypeRaw,
              ] as any
            }
            skipHtml={false}
            components={{
              // Heading components - now using CSS classes
              h1: ({ children }: any) => (
                <h1 className="markdown-h1">
                  <TextWrapper>{children}</TextWrapper>
                </h1>
              ),
              h2: ({ children }: any) => (
                <h2 className="markdown-h2">
                  <TextWrapper>{children}</TextWrapper>
                </h2>
              ),
              h3: ({ children }: any) => (
                <h3 className="markdown-h3">
                  <TextWrapper>{children}</TextWrapper>
                </h3>
              ),
              h4: ({ children }: any) => (
                <h4 className="markdown-h4">
                  <TextWrapper>{children}</TextWrapper>
                </h4>
              ),
              h5: ({ children }: any) => (
                <h5 className="markdown-h5">
                  <TextWrapper>{children}</TextWrapper>
                </h5>
              ),
              h6: ({ children }: any) => (
                <h6 className="markdown-h6">
                  <TextWrapper>{children}</TextWrapper>
                </h6>
              ),
              // Paragraph
              p: ({ children }: any) => (
                <p className="markdown-paragraph">
                  <TextWrapper>{children}</TextWrapper>
                </p>
              ),
              // Horizontal rule
              hr: () => (
                <hr className="markdown-hr" />
              ),
              // Ordered list
              ol: ({ children }: any) => (
                <ol className="markdown-ol">
                  {children}
                </ol>
              ),
              // Unordered list
              ul: ({ children }: any) => (
                <ul className="markdown-ul">
                  {children}
                </ul>
              ),
              // List item
              li: ({ children }: any) => (
                <li className="markdown-li">
                  <TextWrapper>{children}</TextWrapper>
                </li>
              ),
              // Blockquote
              blockquote: ({ children }: any) => (
                <blockquote className="markdown-blockquote">
                  <TextWrapper>{children}</TextWrapper>
                </blockquote>
              ),
              // Table components
              td: ({ children }: any) => (
                <td className="markdown-td">
                  <TextWrapper>{children}</TextWrapper>
                </td>
              ),
              th: ({ children }: any) => (
                <th className="markdown-th">
                  <TextWrapper>{children}</TextWrapper>
                </th>
              ),
              // Emphasis components
              strong: ({ children }: any) => (
                <strong className="markdown-strong">
                  <TextWrapper>{children}</TextWrapper>
                </strong>
              ),
              em: ({ children }: any) => (
                <em className="markdown-em">
                  <TextWrapper>{children}</TextWrapper>
                </em>
              ),
              // Strikethrough
              del: ({ children }: any) => (
                <del className="markdown-del">
                  <TextWrapper>{children}</TextWrapper>
                </del>
              ),
              // Link
              a: ({ href, children, ...props }: any) => {
                return (
                  <a href={href} className="markdown-link" {...props}>
                    <TextWrapper>{children}</TextWrapper>
                  </a>
                );
              },
              pre: ({ children }: any) => <>{children}</>,
              // Code blocks and inline code
              code({ node, inline, className, children, ...props }: any) {
                try {
                  const match = /language-(\w+)/.exec(className || "");
                  const raw = Array.isArray(children)
                    ? children.join("")
                    : children ?? "";
                  const codeContent = String(raw).replace(/^\n+|\n+$/g, "");
                  if (match && match[1]) {
                    // Check if it's a Mermaid diagram
                    if (match[1] === "mermaid") {
                      if (!enableMultimodal) {
                      return renderCodeFallback(codeContent);
                      }
                      return <Diagram code={codeContent} className="my-4" showToggle={showDiagramToggle} />;
                    }
                    if (!inline) {
                      return <CodeBlock codeContent={codeContent} language={match[1]} />;
                    }
                  }
                } catch (error) {
                  // Handle error silently
                }
                return (
                  <code className="markdown-code" {...props}>
                    <TextWrapper>{children}</TextWrapper>
                  </code>
                );
              },
              // Image
              img: ({ src, alt }: any) => (
                <ImageResolver src={src} alt={alt} />
              ),
              // Video
              video: ({ children, ...props }: any) => {
                const directSrc = props?.src;
                const childSource = React.Children.toArray(children)
                  .map((child) =>
                    React.isValidElement(child) ? child.props?.src : undefined
                  )
                  .find(Boolean);
                const videoSrc = directSrc ?? childSource;
                const caption =
                  props?.["aria-label"] ??
                  props?.title ??
                  props?.["data-caption"] ??
                  undefined;

                const element = renderVideoElement({
                  src: videoSrc,
                  alt: caption,
                  props,
                });

                return element ?? renderMediaFallback(undefined, caption);
              },
            }}
          >
            {processedContent}
          </ReactMarkdown>
        </MarkdownErrorBoundary>
      </div>
    </>
  );
};
