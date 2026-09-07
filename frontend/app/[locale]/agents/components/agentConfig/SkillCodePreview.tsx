"use client";

import { type FC, type CSSProperties, useMemo } from "react";
import { useShikiHighlighter, type ShikiHighlighterProps } from "react-shiki";
import { cn } from "@/lib/utils";
import { UNKNOWN_LANGUAGE } from "./skillFileLanguage";
import {
  shouldRenderHighlight,
  type PreviewSizingResult,
} from "./skillPreviewPolicy";

/**
 * Shared Shiki-backed code preview used by Skill surfaces.
 *
 * This component has no dependency on `@assistant-ui/react`. The chat-side
 * `SyntaxHighlighter` in `frontend/app/[locale]/newchat/ui/shiki-highlighter.tsx`
 * reads streaming state from assistant-ui; this component accepts an explicit
 * `isStreaming` prop so it can be reused inside Skill modal panels where
 * assistant-ui is not in scope.
 *
 * Behaviour:
 * - During streaming we render the un-tokenised code in the same container
 *   so layout does not shift when streaming settles.
 * - When the language is unknown or the content exceeds the size threshold
 *   we fall back to plain text. The reason is exposed via `sizing` so callers
 *   can decide whether to surface a hint (we currently do not).
 */
export interface SkillCodePreviewProps {
  code: string;
  /** Shiki language ID such as `python` or `typescript`, never a file path. */
  language?: string | null;
  isStreaming?: boolean;
  /** Delay before settling highlight, forwarded to `react-shiki`. */
  delay?: number;
  className?: string;
  style?: CSSProperties;
  /** Diagnostic sizing decision. Returned via `sizing` for callers. */
  sizing?: PreviewSizingResult;
}

export type SkillCodePreviewSizing = PreviewSizingResult;

const baseContainerClassName =
  "aui-shiki-base [&_pre]:border-border/50 [&_pre]:bg-muted/30 [&_.line]:px-0 [&_pre]:overflow-x-auto [&_pre]:rounded-t-none [&_pre]:rounded-b-xl [&_pre]:border [&_pre]:border-t-0 [&_pre]:p-3.5 [&_pre]:text-[13px] [&_pre]:leading-relaxed";

const streamingContainerClassName =
  "[&_pre]:bg-muted/20 [&_pre]:text-foreground/80";

const PlainCode: FC<{ code: string; language: string | null }> = ({
  code,
  language,
}) => (
  <pre>
    <code data-language={language ?? UNKNOWN_LANGUAGE}>{code}</code>
  </pre>
);

const HighlightedCode: FC<{
  code: string;
  language: string;
  options: Omit<ShikiHighlighterProps, "children" | "language" | "theme">;
}> = ({ code, language, options }) => {
  const highlighted = useShikiHighlighter(code, language, themePair, {
    ...options,
    defaultColor: "light-dark()",
  });
  return <>{highlighted ?? <PlainCode code={code} language={language} />}</>;
};

const themePair: NonNullable<ShikiHighlighterProps["theme"]> = {
  dark: "github-dark-default",
  light: "github-light-default",
};

/**
 * Decide whether to fall back to plain text for a given preview state.
 * Exported so callers can render an inline message when desired.
 */
export function evaluatePreviewSizing(
  content: string,
  lines?: number
): PreviewSizingResult {
  return shouldRenderHighlight({ content, lines });
}

/**
 * Resolve the final language ID to pass to Shiki, mapping unknown inputs to
 * the shared `UNKNOWN_LANGUAGE` constant. Empty languages intentionally fall
 * through so Shiki receives an explicit value rather than `undefined`.
 */
function normaliseLanguage(language?: string | null): string {
  if (!language) return UNKNOWN_LANGUAGE;
  return language.trim() ? language.trim().toLowerCase() : UNKNOWN_LANGUAGE;
}

export const SkillCodePreview: FC<SkillCodePreviewProps> = ({
  code,
  language,
  isStreaming = false,
  delay = 150,
  className,
  style,
}) => {
  const trimmed = useMemo(() => code.replace(/^\n+|\n+$/g, ""), [code]);
  const lineCount = useMemo(
    () => (trimmed ? trimmed.split(/\r?\n/).length : 0),
    [trimmed]
  );
  const sizing = useMemo(
    () => shouldRenderHighlight({ content: trimmed, lines: lineCount }),
    [trimmed, lineCount]
  );

  const resolvedLanguage = normaliseLanguage(language);
  const canHighlight =
    !isStreaming &&
    sizing.shouldHighlight &&
    resolvedLanguage !== UNKNOWN_LANGUAGE;
  return (
    <div
      data-streaming={isStreaming ? "true" : "false"}
      data-highlighted={canHighlight ? "true" : "false"}
      data-sizing-reason={sizing.reason}
      className={cn(
        baseContainerClassName,
        isStreaming && streamingContainerClassName,
        className
      )}
      style={style}
    >
      {canHighlight ? (
        <HighlightedCode
          code={trimmed}
          language={resolvedLanguage}
          options={{ delay }}
        />
      ) : (
        <PlainCode code={trimmed} language={resolvedLanguage} />
      )}
    </div>
  );
};

SkillCodePreview.displayName = "SkillCodePreview";
