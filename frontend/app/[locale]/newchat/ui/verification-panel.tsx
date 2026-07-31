"use client";

import { useState, type FC } from "react";
import {
  CheckIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  LoaderCircleIcon,
  SparklesIcon,
  XCircleIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { VerificationContent } from "../adapter/remote-chat-model-adapter";
import { cn } from "@/lib/utils";

export interface VerificationPanelProps {
  results: VerificationContent[];
  completed: boolean;
}

export const VerificationPanel: FC<VerificationPanelProps> = ({
  results,
  completed,
}) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  const hasBlockingFailure = results.some(
    (result) =>
      result.phase === "blocked" ||
      result.phase === "final_fail" ||
      result.severity === "blocking",
  );
  const HeaderIcon = completed
    ? hasBlockingFailure
      ? CircleAlertIcon
      : CheckIcon
    : LoaderCircleIcon;
  const headerTone = completed
    ? hasBlockingFailure
      ? "text-red-600 dark:text-red-400"
      : "text-emerald-700 dark:text-emerald-400"
    : "text-blue-600 dark:text-blue-400";
  const headerLabel = completed ? "自检完成" : "自检中";

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="my-3 w-full">
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-left text-sm font-medium transition-colors hover:bg-muted/60"
        >
          <HeaderIcon
            className={cn(
              "size-4 shrink-0",
              headerTone,
              !completed && "animate-spin",
            )}
          />
          <span className={headerTone}>{headerLabel}</span>
          <span className="text-xs text-muted-foreground">
            {results.length > 0 ? `${results.length} 项检查` : "正在准备检查"}
          </span>
          <ChevronDownIcon
            className={cn(
              "ml-auto size-4 text-muted-foreground transition-transform",
              open && "rotate-180",
            )}
          />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="border-x border-b px-3 py-2">
          {results.map((result, index) => {
            const phase = result.phase || "start";
            const isFailure =
              phase === "blocked" ||
              phase === "final_fail" ||
              result.severity === "blocking";
            const isWarning = phase === "warning" || phase === "repair";
            const ResultIcon = isFailure
              ? XCircleIcon
              : isWarning
                ? CircleAlertIcon
                : result.passed
                  ? CheckIcon
                  : SparklesIcon;
            const tone = isFailure
              ? "text-red-600 dark:text-red-400"
              : isWarning
                ? "text-amber-600 dark:text-amber-400"
                : "text-muted-foreground";
            const message =
              result.message ||
              result.user_visible_note ||
              result.repair_instruction ||
              t("taskWindow.verification.start");

            return (
              <div
                key={`${result.round}-${result.event}-${result.phase}-${index}`}
                className="flex items-start gap-2 py-1.5 text-sm"
              >
                <ResultIcon className={cn("mt-0.5 size-4 shrink-0", tone)} />
                <span className={cn("min-w-0 flex-1", tone)}>{message}</span>
                {typeof result.score === "number" && (
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {Math.round(result.score * 100)}%
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};
