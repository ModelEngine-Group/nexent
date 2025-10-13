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
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { SearchResult } from "@/types/chat";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { CopyButton } from "@/components/ui/copyButton";

interface MarkdownRendererProps {
  content: string;
  className?: string;
  searchResults?: SearchResult[];
}

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
}: {
  text: string;
  searchResults?: SearchResult[];
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
      const tooltipContent = document.querySelector(".z-\\[9999\\]");
      const linkElement = containerRef.current;

      if (!tooltipContent || !linkElement) {
        setIsOpen(false);
        return;
      }

      const tooltipRect = tooltipContent.getBoundingClientRect();
      const linkRect = linkElement.getBoundingClientRect();
      const { x: mouseX, y: mouseY } = mousePositionRef.current;

      // Check if mouse is over tooltip or link icon
      const isMouseOverTooltip =
        mouseX >= tooltipRect.left &&
        mouseX <= tooltipRect.right &&
        mouseY >= tooltipRect.top &&
        mouseY <= tooltipRect.bottom;

      const isMouseOverLink =
        mouseX >= linkRect.left &&
        mouseX <= linkRect.right &&
        mouseY >= linkRect.top &&
        mouseY <= linkRect.bottom;

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
  }, [isOpen]);

  return (
    <TooltipProvider>
      <Tooltip open={isOpen}>
        <span
          ref={containerRef}
          className="inline-flex items-center relative"
          style={{ zIndex: isOpen ? 1000 : "auto" }}
        >
          <TooltipTrigger asChild>
            <span className="inline-flex items-center cursor-pointer transition-colors">
              <CitationBadge toolSign={toolSign} citeIndex={citeIndex} />
            </span>
          </TooltipTrigger>
          {/* Force Portal to body */}
          <TooltipPrimitive.Portal>
            <TooltipContent
              side="top"
              align="center"
              sideOffset={5}
              className="z-[9999] bg-white px-3 py-2 text-sm border shadow-md max-w-md"
              style={
                {
                  "--scrollbar-width": "8px",
                  "--scrollbar-height": "8px",
                  "--scrollbar-track-bg": "transparent",
                  "--scrollbar-thumb-bg": "rgb(209, 213, 219)",
                  "--scrollbar-thumb-hover-bg": "rgb(156, 163, 175)",
                  "--scrollbar-thumb-radius": "9999px",
                } as React.CSSProperties
              }
            >
              <div
                ref={tooltipRef}
                className="whitespace-pre-wrap overflow-y-auto"
                style={{
                  maxHeight: 240,
                  minWidth: 200,
                  maxWidth: 400,
                  scrollbarWidth: "thin",
                  scrollbarColor:
                    "var(--scrollbar-thumb-bg) var(--scrollbar-track-bg)",
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
            </TooltipContent>
          </TooltipPrimitive.Portal>
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
  
  return content
    // Convert \( ... \) to $ ... $ (inline math)
    .replace(/\\\(([\s\S]*?)\\\)/g, '$$1$')
    // Convert \[ ... \] to $$ ... $$ (display math)
    .replace(/\\\[([\s\S]*?)\\\]/g, '$$$$1$$\n');
};

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className,
  searchResults = [],
}) => {
  const { t } = useTranslation("common");

  // Convert LaTeX delimiters to markdown math delimiters
  const processedContent = convertLatexDelimiters(content);

  // Customize code block style with light gray background
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

  // Modified processText function logic
  const processText = (text: string) => {
    if (typeof text !== "string") return text;

    const parts = text.split(/(\[\[[^\]]+\]\])/g);
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
                />
              );
            } else {
              // Return empty string if no matching result found (display nothing)
              return "";
            }
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
              a: ({ href, children, ...props }: any) => (
                <a href={href} className="markdown-link" {...props}>
                  <TextWrapper>{children}</TextWrapper>
                </a>
              ),
              pre: ({ children }: any) => <>{children}</>,
              // Code blocks and inline code
              code({ node, inline, className, children, ...props }: any) {
                try {
                  const match = /language-(\w+)/.exec(className || "");
                  const raw = Array.isArray(children)
                    ? children.join("")
                    : children ?? "";
                  const codeContent = String(raw).replace(/^\n+|\n+$/g, "");
                  if (!inline && match && match[1]) {
                    return (
                      <div className="code-block-container group">
                        <div className="code-block-header">
                          <span
                            className="code-language-label"
                            data-language={match[1]}
                          >
                            {match[1]}
                          </span>
                          <CopyButton
                            content={codeContent}
                            variant="code-block"
                            className="header-copy-button"
                            tooltipText={{
                              copy: t("chatStreamMessage.copyContent"),
                              copied: t("chatStreamMessage.copied"),
                            }}
                          />
                        </div>
                        <div className="code-block-content">
                          <SyntaxHighlighter
                            style={customStyle}
                            language={match[1]}
                            PreTag="div"
                            {...props}
                          >
                            {codeContent}
                          </SyntaxHighlighter>
                        </div>
                      </div>
                    );
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
                <img src={src} alt={alt} className="markdown-img" />
              ),
            }}
          >
            {processedContent}
          </ReactMarkdown>
        </MarkdownErrorBoundary>
      </div>
    </>
  );
};
