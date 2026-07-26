"use client";

import {
  memo,
  type ComponentProps,
  type FC,
} from "react";
import {
  ComposerPrimitive,
  SelectionToolbarPrimitive,
  type QuoteMessagePartComponent,
} from "@assistant-ui/react";
import { QuoteIcon, XIcon } from "lucide-react";

import { cn } from "@/lib/utils";

function QuoteBlockRoot({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="quote-block-root"
      className={cn(
        "border-muted-foreground/30 text-muted-foreground mb-2 flex items-start gap-2 border-l-2 pl-2 text-sm italic",
        className
      )}
      {...props}
    />
  );
}

function QuoteBlockIcon({
  className,
  ...props
}: ComponentProps<"span">) {
  return (
    <QuoteIcon
      data-slot="quote-block-icon"
      className={cn("mt-0.5 size-3.5 shrink-0", className)}
      {...(props as ComponentProps<typeof QuoteIcon>)}
    />
  );
}

function QuoteBlockText({ className, ...props }: ComponentProps<"p">) {
  return (
    <p
      data-slot="quote-block-text"
      className={cn("line-clamp-2 min-w-0 flex-1", className)}
      {...props}
    />
  );
}

/**
 * Renders quoted text in user messages.
 *
 * Pass to `MessagePrimitive.Quote` via the `children` render function.
 *
 * @example
 * ```tsx
 * <MessagePrimitive.Quote>
 *   {(quote) => <QuoteBlock {...quote} />}
 * </MessagePrimitive.Quote>
 * ```
 */
const QuoteBlockImpl: QuoteMessagePartComponent = ({ text }) => {
  return (
    <QuoteBlockRoot>
      <QuoteBlockIcon />
      <QuoteBlockText>{text}</QuoteBlockText>
    </QuoteBlockRoot>
  );
};

const QuoteBlock = memo(
  QuoteBlockImpl,
) as unknown as QuoteMessagePartComponent & {
  Root: typeof QuoteBlockRoot;
  Icon: typeof QuoteBlockIcon;
  Text: typeof QuoteBlockText;
};

QuoteBlock.displayName = "QuoteBlock";
QuoteBlock.Root = QuoteBlockRoot;
QuoteBlock.Icon = QuoteBlockIcon;
QuoteBlock.Text = QuoteBlockText;

function SelectionToolbarRoot({
  className,
  ...props
}: ComponentProps<typeof SelectionToolbarPrimitive.Root>) {
  return (
    <SelectionToolbarPrimitive.Root
      data-slot="selection-toolbar"
      className={cn(
        "bg-popover flex items-center gap-1 rounded-lg border px-1 py-1 shadow-md",
        className
      )}
      {...props}
    />
  );
}

function SelectionToolbarQuote({
  className,
  children,
  ...props
}: ComponentProps<typeof SelectionToolbarPrimitive.Quote>) {
  return (
    <SelectionToolbarPrimitive.Quote
      data-slot="selection-toolbar-quote"
      className={cn(
        "text-popover-foreground hover:bg-accent flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm transition-colors",
        className
      )}
      {...props}
    >
      {children ?? (
        <>
          <QuoteIcon className="size-3.5" />
          Quote
        </>
      )}
    </SelectionToolbarPrimitive.Quote>
  );
}

/**
 * Floating toolbar that appears when text is selected in a message.
 *
 * Render inside `ThreadPrimitive.Root` (or any `AssistantRuntimeProvider` scope).
 */
const SelectionToolbarImpl: FC<
  ComponentProps<typeof SelectionToolbarPrimitive.Root>
> = ({ className, ...props }) => {
  return (
    <SelectionToolbarRoot className={className} {...props}>
      <SelectionToolbarQuote />
    </SelectionToolbarRoot>
  );
};

const SelectionToolbar = memo(SelectionToolbarImpl) as unknown as typeof SelectionToolbarImpl & {
  Root: typeof SelectionToolbarRoot;
  Quote: typeof SelectionToolbarQuote;
};

SelectionToolbar.displayName = "SelectionToolbar";
SelectionToolbar.Root = SelectionToolbarRoot;
SelectionToolbar.Quote = SelectionToolbarQuote;

function ComposerQuotePreviewRoot({
  className,
  ...props
}: ComponentProps<typeof ComposerPrimitive.Quote>) {
  return (
    <ComposerPrimitive.Quote
      data-slot="composer-quote"
      className={cn(
        "bg-muted/60 mx-3 mt-2 flex items-start gap-2 rounded-lg px-3 py-2",
        className
      )}
      {...props}
    />
  );
}

function ComposerQuotePreviewIcon({
  className,
  ...props
}: ComponentProps<"span">) {
  return (
    <QuoteIcon
      data-slot="composer-quote-icon"
      className={cn("mt-0.5 size-3.5 shrink-0", className)}
      {...(props as ComponentProps<typeof QuoteIcon>)}
    />
  );
}

function ComposerQuotePreviewText({
  className,
  ...props
}: ComponentProps<typeof ComposerPrimitive.QuoteText>) {
  return (
    <ComposerPrimitive.QuoteText
      data-slot="composer-quote-text"
      className={cn(
        "text-muted-foreground line-clamp-2 min-w-0 flex-1 text-sm",
        className
      )}
      {...props}
    />
  );
}

function ComposerQuotePreviewDismiss({
  className,
  children,
  ...props
}: ComponentProps<typeof ComposerPrimitive.QuoteDismiss>) {
  return (
    <ComposerPrimitive.QuoteDismiss
      data-slot="composer-quote-dismiss"
      asChild
      className={children ? className : undefined}
      {...props}
    >
      {children ?? (
        <button
          type="button"
          aria-label="Dismiss quote"
          className="hover:bg-accent text-muted-foreground/70 hover:text-foreground shrink-0 rounded-sm p-0.5 transition-colors"
        >
          <XIcon className="size-3.5" />
        </button>
      )}
    </ComposerPrimitive.QuoteDismiss>
  );
}

/**
 * Quote preview inside the composer. Only renders when a quote is set.
 *
 * Place inside `ComposerPrimitive.Root`.
 */
const ComposerQuotePreviewImpl: FC<
  ComponentProps<typeof ComposerPrimitive.Quote>
> = ({ className, ...props }) => {
  return (
    <ComposerQuotePreviewRoot className={className} {...props}>
      <ComposerQuotePreviewIcon />
      <ComposerQuotePreviewText />
      <ComposerQuotePreviewDismiss />
    </ComposerQuotePreviewRoot>
  );
};

const ComposerQuotePreview = memo(
  ComposerQuotePreviewImpl,
) as unknown as typeof ComposerQuotePreviewImpl & {
  Root: typeof ComposerQuotePreviewRoot;
  Icon: typeof ComposerQuotePreviewIcon;
  Text: typeof ComposerQuotePreviewText;
  Dismiss: typeof ComposerQuotePreviewDismiss;
};

ComposerQuotePreview.displayName = "ComposerQuotePreview";
ComposerQuotePreview.Root = ComposerQuotePreviewRoot;
ComposerQuotePreview.Icon = ComposerQuotePreviewIcon;
ComposerQuotePreview.Text = ComposerQuotePreviewText;
ComposerQuotePreview.Dismiss = ComposerQuotePreviewDismiss;

export {
  QuoteBlock,
  QuoteBlockRoot,
  QuoteBlockIcon,
  QuoteBlockText,
  SelectionToolbar,
  SelectionToolbarRoot,
  SelectionToolbarQuote,
  ComposerQuotePreview,
  ComposerQuotePreviewRoot,
  ComposerQuotePreviewIcon,
  ComposerQuotePreviewText,
  ComposerQuotePreviewDismiss,
};
