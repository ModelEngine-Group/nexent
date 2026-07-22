"use client";

import { memo, useMemo } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { BrainIcon, ChevronDownIcon } from "lucide-react";
import {
  type ReasoningMessagePartComponent,
  useAuiState,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import ReactMarkdown from "react-markdown";
import { defaultComponents } from "./markdown-text";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

/**
 * Extracts the step label from the leading markdown heading of a reasoning
 * part's text. The backend prepends `**步骤 N**` / `**Step N**` markers via
 * the `step_count` chunk; both the SSE stream and history paths fold that
 * marker into the same reasoning text, so this single extraction works for
 * both sources.
 */
const STEP_LABEL_RE = /^\s*\*\*(.+?)\*\*\s*/;

export function extractStepLabel(text: string | undefined): string | undefined {
  if (!text) return undefined;
  const m = text.match(STEP_LABEL_RE);
  return m ? m[1].trim() : undefined;
}

/**
 * Strips the leading step label marker from a reasoning text so the body
 * renders without the duplicated `**步骤 N**` heading.
 */
export function stripStepLabel(text: string): string {
  return text.replace(STEP_LABEL_RE, "");
}

const CODE_TAG_RE = /<code>([\s\S]*?)(<\/code>|$)/gi;
const BACKTICK_RUN_RE = /`+/g;

export function normalizeReasoningCodeBlocks(text: string): string {
  return text.replace(CODE_TAG_RE, (_, rawCode: string, closingTag: string) => {
    let code = rawCode.replace(/^\r?\n/, "");
    if (closingTag) {
      code = code.replace(/\r?\n$/, "");
    }
    const longestBacktickRun = Math.max(
      0,
      ...Array.from(code.matchAll(BACKTICK_RUN_RE), (match) => match[0].length),
    );
    const fence = "`".repeat(Math.max(3, longestBacktickRun + 1));

    return `\n\n${fence}\n${code}\n${fence}\n\n`;
  });
}

interface StreamingReasoningSegment {
  type: "text" | "code";
  content: string;
}

function splitStreamingReasoning(text: string): StreamingReasoningSegment[] {
  const segments: StreamingReasoningSegment[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  CODE_TAG_RE.lastIndex = 0;
  while ((match = CODE_TAG_RE.exec(text)) !== null) {
    if (match.index > cursor) {
      segments.push({
        type: "text",
        content: text.slice(cursor, match.index),
      });
    }

    segments.push({
      type: "code",
      content: match[1].replace(/^\r?\n/, ""),
    });
    cursor = CODE_TAG_RE.lastIndex;
  }

  if (cursor < text.length) {
    segments.push({ type: "text", content: text.slice(cursor) });
  }

  return segments;
}

const reasoningVariants = cva(
  "aui-reasoning-root my-2 w-full overflow-hidden rounded-xl",
  {
    variants: {
      variant: {
        outline: "border border-border/60 bg-card",
        ghost: "",
        muted: "rounded-xl bg-muted/40",
      },
    },
    defaultVariants: {
      variant: "outline",
    },
  }
);

export type ReasoningRootProps = Omit<
  React.ComponentProps<"div">,
  "open" | "onOpenChange"
> &
  VariantProps<typeof reasoningVariants> & {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    defaultOpen?: boolean;
  };

function ReasoningRoot({
  className,
  variant,
  open,
  onOpenChange,
  defaultOpen,
  children,
  ...props
}: ReasoningRootProps) {
  return (
    <Collapsible
      open={open}
      onOpenChange={onOpenChange}
      defaultOpen={defaultOpen}
    >
      <div className={cn(reasoningVariants({ variant }), className)} {...props}>
        {children}
      </div>
    </Collapsible>
  );
}

function ReasoningFade({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent to-background",
        className
      )}
      {...props}
    />
  );
}

function ReasoningTrigger({
  active,
  duration,
  label,
  thinkingLabel,
  text,
  className,
  ...props
}: React.ComponentProps<"button"> & {
  active?: boolean;
  duration?: number;
  label?: string;
  thinkingLabel?: string;
  /**
   * Full reasoning text including any leading `**步骤 N**` marker. The marker
   * is extracted at render time and used as the trigger label when no
   * explicit `label` is provided. Works identically for live SSE and history.
   */
  text?: string;
}) {
  const durationText = duration ? ` (${duration}s)` : "";
  const displayLabel = label ?? extractStepLabel(text);

  return (
    <CollapsibleTrigger asChild>
      <button
        className={cn(
          "flex w-full cursor-pointer items-center gap-2 rounded-t-xl px-3 py-2 text-sm font-medium transition-colors hover:bg-muted/40 data-[state=open]:[&_svg.chevron]:rotate-180",
          className
        )}
        {...props}
      >
        <BrainIcon className="size-4" />
        <span>{displayLabel ?? "Reasoning"}{durationText}</span>
        {active ? (
          <span className="text-muted-foreground text-xs">
            ({thinkingLabel ?? "Thinking..."})
          </span>
        ) : null}
        <ChevronDownIcon className="chevron ml-auto size-4 transition-transform duration-200" />
      </button>
    </CollapsibleTrigger>
  );
}

/**
 * Grouped-reasoning trigger used by `MessagePrimitive.GroupedParts`. We do
 * NOT derive the label from the message's reasoning parts here: each group
 * contains its own reasoning subset and reading "the first reasoning part"
 * globally causes every group to show the same step label (e.g. "步骤 1"
 * leaking into the second/third group). Instead, leave the label as
 * `undefined` so the underlying `ReasoningTrigger` falls back to its default
 * `Reasoning` text. The step label is still rendered inside each group's
 * body because `step_count` chunks are folded into the reasoning text by
 * both adapters.
 */
function GroupReasoningTrigger({
  active,
  duration,
  label,
  thinkingLabel,
  className,
  ...props
}: Omit<Parameters<typeof ReasoningTrigger>[0], "text">) {
  return (
    <ReasoningTrigger
      active={active}
      duration={duration}
      label={label}
      thinkingLabel={thinkingLabel}
      className={className}
      {...props}
    />
  );
}

function ReasoningContent({
  className,
  children,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <CollapsibleContent>
      <div className={cn("border-t border-border/60 px-3 py-2", className)} {...props}>
        {children}
      </div>
    </CollapsibleContent>
  );
}

function ReasoningText({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div className={cn("text-muted-foreground/90 text-sm leading-relaxed", className)} {...props} />
  );
}

const StreamingMarkdownSegment = memo(({ content }: { content: string }) => (
  <ReactMarkdown
    className="aui-md prose prose-sm max-w-none text-sm leading-relaxed text-muted-foreground/90 dark:prose-invert"
    components={{
      p: ({ children }) => <p className="my-3 first:mt-0 last:mb-0">{children}</p>,
      a: ({ children, href }) => (
        <a
          className="text-primary hover:text-primary/80 underline underline-offset-2"
          href={href}
        >
          {children}
        </a>
      ),
      blockquote: ({ children }) => (
        <blockquote className="border-muted-foreground/30 text-muted-foreground my-3 border-s-2 ps-4">
          {children}
        </blockquote>
      ),
      ul: ({ children }) => (
        <ul className="marker:text-muted-foreground my-3 ms-5 list-disc [&>li]:mt-1">
          {children}
        </ul>
      ),
      ol: ({ children }) => (
        <ol className="marker:text-muted-foreground my-3 ms-5 list-decimal [&>li]:mt-1">
          {children}
        </ol>
      ),
      li: ({ children }) => <li className="leading-relaxed">{children}</li>,
      strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
      code: ({ children }) => (
        <code className="bg-muted rounded-md px-1.5 py-0.5 font-mono text-[0.85em]">
          {children}
        </code>
      ),
    }}
  >
    {content}
  </ReactMarkdown>
));

StreamingMarkdownSegment.displayName = "StreamingMarkdownSegment";

const StreamingReasoning = () => {
  const text = useAuiState((s) =>
    s.part?.type === "reasoning" ? s.part.text : "",
  );
  const isRunning = useAuiState(
    (s) => s.part?.type === "reasoning" && s.part.status.type === "running",
  );
  const segments = useMemo(() => splitStreamingReasoning(text), [text]);

  if (!isRunning) {
    return (
      <MarkdownTextPrimitive
        className="aui-md prose prose-sm max-w-none dark:prose-invert"
        components={defaultComponents}
        preprocess={normalizeReasoningCodeBlocks}
      />
    );
  }

  return (
    <div className="aui-streaming-reasoning space-y-3 text-sm leading-relaxed text-muted-foreground/90">
      {segments.map((segment, index) =>
        segment.type === "code" ? (
          <pre
            key={`code-${index}`}
            className="aui-md-pre border-border/50 bg-muted/30 overflow-x-auto rounded-xl border p-3.5 text-[13px] leading-relaxed whitespace-pre"
          >
            <code>{segment.content}</code>
          </pre>
        ) : (
          <StreamingMarkdownSegment
            key={`text-${index}`}
            content={segment.content}
          />
        ),
      )}
    </div>
  );
};

const ReasoningImpl: ReasoningMessagePartComponent = () => <StreamingReasoning />;

const Reasoning = memo(
  ReasoningImpl,
) as unknown as ReasoningMessagePartComponent & {
  Root: typeof ReasoningRoot;
  Trigger: typeof ReasoningTrigger;
  Content: typeof ReasoningContent;
  Text: typeof ReasoningText;
  Fade: typeof ReasoningFade;
};

Reasoning.displayName = "Reasoning";
Reasoning.Root = ReasoningRoot;
Reasoning.Trigger = ReasoningTrigger;
Reasoning.Content = ReasoningContent;
Reasoning.Text = ReasoningText;
Reasoning.Fade = ReasoningFade;

/**
 * Used by grouped-reasoning renderers (`MessagePrimitive.GroupedParts`)
 * where each group owns its own subset of reasoning parts. The trigger
 * deliberately leaves the label unset so the underlying `ReasoningTrigger`
 * falls back to the default `Reasoning` text. The actual step label
 * (e.g. `**步骤 N**`) lives inside the reasoning body, folded there by the
 * streaming and history adapters.
 */
export { GroupReasoningTrigger };

export { Reasoning };
