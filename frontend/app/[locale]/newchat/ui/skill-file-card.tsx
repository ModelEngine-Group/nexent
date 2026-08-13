"use client";

import { useState, type FC } from "react";
import {
  CheckIcon,
  ChevronDownIcon,
  FileCode2Icon,
  FileTextIcon,
  PlayIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { Nl2SkillFileCardData } from "../adapter/remote-chat-model-adapter";
import { SkillCodePreview } from "../../agents/components/agentConfig/SkillCodePreview";

export const SkillFileCard: FC<{
  data: Nl2SkillFileCardData;
  onSkillFileSelect?: (path: string) => void;
}> = ({ data, onSkillFileSelect }) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const pathParts = data.path.split("/");
  const filename = pathParts.pop() || data.path;
  const directory = pathParts.join("/");
  const isCode = data.kind === "code";
  const FileIcon = isCode ? FileCode2Icon : FileTextIcon;

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="my-3 overflow-hidden rounded-xl border bg-card shadow-sm"
    >
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/40"
        >
          <FileIcon className="size-5 shrink-0 text-primary" />
          <span className="min-w-0 flex-1">
            {directory ? (
              <span className="block truncate text-xs text-muted-foreground">
                {directory}/
              </span>
            ) : null}
            <span className="block truncate text-sm font-medium">
              {filename}
            </span>
          </span>
          {data.isStreaming ? (
            <span className="size-2 animate-pulse rounded-full bg-primary" />
          ) : null}
          <ChevronDownIcon
            className={cn("size-4 transition-transform", open && "rotate-180")}
          />
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="max-h-96 overflow-auto border-t bg-muted/20 p-3">
          {data.kind === "markdown" ? (
            <MarkdownRenderer
              content={data.content}
              className="text-sm"
              enableSkillDirectives
              onSkillDirectiveClick={onSkillFileSelect}
            />
          ) : data.kind === "code" ? (
            <SkillCodePreview
              code={data.content}
              language={data.language || "text"}
              isStreaming={data.isStreaming}
            />
          ) : (
            <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">
              {data.content}
            </pre>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t px-3 py-2">
          {isCode ? (
            <Button type="button" size="sm" variant="outline" disabled>
              <PlayIcon className="size-3.5" />
              {t("skillManagement.fileCard.run")}
            </Button>
          ) : null}
          <Button type="button" size="sm" disabled>
            <CheckIcon className="size-3.5" />
            {t("common.confirm")}
          </Button>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};
