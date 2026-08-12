"use client";

import { memo } from "react";
import { useSourcesPanel } from "./sources-panel-context";
import type { PanelSourceItem } from "./sources-panel";
import {
  AlertCircleIcon,
  CheckIcon,
  ChevronDownIcon,
  LoaderIcon,
  XCircleIcon,
} from "lucide-react";
import {
  type ToolCallMessagePartStatus,
  type ToolCallMessagePartProps,
  type ToolCallMessagePartComponent,
} from "@assistant-ui/react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { AuthenticatedImage } from "./authenticated-image";
import { SourceIcon, SourceTitle } from "./sources";

const statusIconMap: Record<string, typeof LoaderIcon> = {
  running: LoaderIcon,
  complete: CheckIcon,
  incomplete: XCircleIcon,
  "requires-action": AlertCircleIcon,
};

export type ToolFallbackRootProps = Omit<
  React.ComponentProps<"div">,
  "open" | "onOpenChange"
> & {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  defaultOpen?: boolean;
};

function ToolFallbackRoot({
  className,
  children,
  ...props
}: ToolFallbackRootProps) {
  return (
    <Collapsible className={cn("mb-4 w-full", className)} {...props}>
      {children}
    </Collapsible>
  );
}

function ToolFallbackTrigger({
  toolName,
  status,
  className,
  ...props
}: React.ComponentProps<"button"> & {
  toolName: string;
  status?: ToolCallMessagePartStatus;
}) {
  const statusType = status?.type ?? "complete";
  const isRunning = statusType === "running";
  const isCancelled =
    status?.type === "incomplete" && status.reason === "cancelled";

  const Icon = statusIconMap[statusType];
  const label = isCancelled ? "Cancelled tool" : "Used tool";

  return (
    <CollapsibleTrigger asChild>
      <button
        className={cn(
          "flex w-full cursor-pointer items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium hover:bg-muted/50",
          className
        )}
        {...props}
      >
        <Icon className={cn("size-4", isRunning && "animate-spin")} />
        <span>
          {label}: {toolName}
        </span>
        {isRunning && (
          <span className="ml-auto text-xs text-muted-foreground">
            {label}: {toolName}
          </span>
        )}
      </button>
    </CollapsibleTrigger>
  );
}

function ToolFallbackContent({
  className,
  children,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <CollapsibleContent>
      <div
        className={cn("rounded-b-lg border border-t-0 p-4", className)}
        {...props}
      >
        {children}
      </div>
    </CollapsibleContent>
  );
}

function ToolFallbackArgs({
  argsText,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  argsText?: string;
}) {
  if (!argsText) return null;

  return (
    <div className={cn("mb-2", className)} {...props}>
      <div className="mb-1 text-xs font-medium text-muted-foreground">
        Arguments:
      </div>
      <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">
        {argsText}
      </pre>
    </div>
  );
}

function ToolFallbackResult({
  result,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  result?: unknown;
}) {
  if (result === undefined) return null;

  return (
    <div className={cn("", className)} {...props}>
      <div className="mb-1 text-xs font-medium text-muted-foreground">
        Result:
      </div>
      <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">
        {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
      </pre>
    </div>
  );
}

function ToolFallbackError({
  status,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  status?: ToolCallMessagePartStatus;
}) {
  if (status?.type !== "incomplete") return null;

  const error = status.error;
  const errorText = error
    ? typeof error === "string"
      ? error
      : JSON.stringify(error)
    : null;

  if (!errorText) return null;

  const isCancelled = status.reason === "cancelled";
  const headerText = isCancelled ? "Cancelled reason:" : "Error:";

  return (
    <div className={cn("mt-2 text-destructive", className)} {...props}>
      <div className="mb-1 text-xs font-medium">{headerText}</div>
      <pre className="overflow-x-auto rounded bg-destructive/10 p-2 text-xs">
        {errorText}
      </pre>
    </div>
  );
}

type ToolSearchSource = {
  url?: string;
  title?: string;
  text?: string;
  sourceType?: string;
  filename?: string;
  sourceFile?: string;
  objectName?: string;
  citeIndex?: number;
  toolSign?: string;
  isImage?: boolean;
};

function ToolFallbackSearchContent({
  searchContent,
  searchImages,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  searchContent?: ToolSearchSource[];
  searchImages?: string[];
}) {
  const { open } = useSourcesPanel();
  const imageSources = [
    ...(searchImages ?? []).map((url) => ({ url, title: url, isImage: true })),
    ...(searchContent ?? []).filter((item) => item.isImage),
  ].filter(
    (item, index, items) =>
      item.url &&
      items.findIndex((candidate) => candidate.url === item.url) === index
  );
  const regularSources = (searchContent ?? []).filter((item) => !item.isImage);
  const panelSources: PanelSourceItem[] = regularSources.map((item, index) => ({
    sourceType:
      item.sourceType === "file" || item.sourceType === "document" || item.filename || item.objectName
        ? "document"
        : "url",
    url: item.url,
    title: item.title || item.filename || item.sourceFile || item.url,
    text: item.text,
    filename: item.filename || item.sourceFile,
    objectName: item.objectName,
    citeIndex: item.citeIndex ?? index,
    toolSign: item.toolSign,
  }));
  const hasContent = imageSources.length > 0 || regularSources.length > 0;
  if (!hasContent) return null;

  return (
    <div className={cn("mt-2", className)} {...props}>
      <div className="mb-1 text-xs font-medium text-muted-foreground">
        Sources:
      </div>
      {imageSources.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {imageSources.map((item, index) => (
            <div
              key={`img-${item.url}-${index}`}
              className="aui-tool-fallback-search-image block overflow-hidden rounded-md border bg-muted/50"
              title={item.title || item.url}
            >
              <AuthenticatedImage
                src={item.url!}
                alt={item.title || item.url}
                loading="lazy"
                preview
                className="size-20 object-cover"
              />
            </div>
          ))}
        </div>
      )}
      {regularSources.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {regularSources.map((item, index) => {
            return (
              <button
                key={`src-${item.url}-${index}`}
                type="button"
                className="inline-flex"
                onClick={() =>
                  open({
                    messageId: "tool-search",
                    groupId: `tool-search-${index}`,
                    sources: panelSources,
                    images: [],
                    selectedCitationKey: `${item.toolSign ?? ""}${item.citeIndex ?? index}`,
                  })
                }
              >
                <span className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border bg-secondary px-2 py-1 text-xs text-secondary-foreground transition-colors hover:bg-secondary/80">
                  <SourceIcon url={item.url || ""} />
                  <SourceTitle>{item.title || item.url || "Source"}</SourceTitle>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

const ToolFallbackImpl = ({
  toolName,
  argsText,
  result,
  status,
  searchContent,
  searchImages,
}: ToolCallMessagePartProps & {
  searchContent?: ToolSearchSource[];
  searchImages?: string[];
}) => {
  const isCancelled =
    status?.type === "incomplete" && status.reason === "cancelled";

  return (
    <ToolFallbackRoot>
      <ToolFallbackTrigger toolName={toolName} status={status} />
      {!isCancelled && (
        <ToolFallbackContent>
          <ToolFallbackArgs argsText={argsText} />
          <ToolFallbackResult result={result} />
          <ToolFallbackSearchContent
            searchContent={searchContent}
            searchImages={searchImages}
          />
          <ToolFallbackError status={status} />
        </ToolFallbackContent>
      )}
    </ToolFallbackRoot>
  );
};

const ToolFallback = memo(
  ToolFallbackImpl
) as unknown as ToolCallMessagePartComponent & {
  Root: typeof ToolFallbackRoot;
  Trigger: typeof ToolFallbackTrigger;
  Content: typeof ToolFallbackContent;
  Args: typeof ToolFallbackArgs;
  Result: typeof ToolFallbackResult;
  Error: typeof ToolFallbackError;
  SearchContent: typeof ToolFallbackSearchContent;
};

ToolFallback.displayName = "ToolFallback";
ToolFallback.Root = ToolFallbackRoot;
ToolFallback.Trigger = ToolFallbackTrigger;
ToolFallback.Content = ToolFallbackContent;
ToolFallback.Args = ToolFallbackArgs;
ToolFallback.Result = ToolFallbackResult;
ToolFallback.Error = ToolFallbackError;
ToolFallback.SearchContent = ToolFallbackSearchContent;

export { ToolFallback };
