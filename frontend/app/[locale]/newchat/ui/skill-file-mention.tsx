"use client";

import { useMemo, type FC } from "react";
import {
  ComposerPrimitive,
  unstable_useMentionAdapter,
  type Unstable_Mention,
} from "@assistant-ui/react";
import { FileQuestion, FolderSymlink, SquareCode } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SkillFileContent } from "@/types/skill";
import {
  SKILL_REFERENCE_DIRECTIVE_TYPE,
  SKILL_SCRIPT_DIRECTIVE_TYPE,
  normalizeSkillDirectivePath,
  skillDirectiveFormatter,
  skillDirectiveIconMap,
} from "./skill-directives";

interface SkillFileMentionPopoverProps {
  files: readonly SkillFileContent[];
}

function toMention(file: SkillFileContent): Unstable_Mention | null {
  const normalizedPath = normalizeSkillDirectivePath(file.path);
  if (!normalizedPath || normalizedPath.toLowerCase() === "skill.md") {
    return null;
  }

  const extension = normalizedPath.split(".").at(-1)?.toLowerCase();
  const isReference = extension === "md";
  const isScript = extension === "sh" || extension === "py";
  if (!isReference && !isScript) return null;

  return {
    id: normalizedPath,
    type: isReference
      ? SKILL_REFERENCE_DIRECTIVE_TYPE
      : SKILL_SCRIPT_DIRECTIVE_TYPE,
    label: normalizedPath.split("/").at(-1) || normalizedPath,
    description: normalizedPath,
    icon: isReference
      ? SKILL_REFERENCE_DIRECTIVE_TYPE
      : SKILL_SCRIPT_DIRECTIVE_TYPE,
  };
}

export const SkillFileMentionPopover: FC<SkillFileMentionPopoverProps> = ({
  files,
}) => {
  const { t } = useTranslation("common");
  const items = useMemo(
    () =>
      files
        .map(toMention)
        .filter((item): item is Unstable_Mention => item !== null)
        .filter(
          (item, index, all) =>
            all.findIndex((candidate) => candidate.id === item.id) === index
        )
        .sort((left, right) => {
          if (left.type !== right.type) {
            return left.type === SKILL_REFERENCE_DIRECTIVE_TYPE ? -1 : 1;
          }
          return left.id.localeCompare(right.id);
        }),
    [files]
  );
  const mention = unstable_useMentionAdapter({
    items,
    includeModelContextTools: false,
    formatter: skillDirectiveFormatter,
    iconMap: skillDirectiveIconMap,
  });

  return (
    <ComposerPrimitive.Unstable_TriggerPopover
      char="@"
      adapter={mention.adapter}
      aria-label={t("skillManagement.mentions.files", {
        defaultValue: "Skill files",
      })}
      className="absolute bottom-full left-3 right-3 z-50 mb-2 max-h-64 overflow-hidden rounded-xl border border-border bg-popover text-popover-foreground shadow-lg"
    >
      <ComposerPrimitive.Unstable_TriggerPopover.Directive
        formatter={mention.directive.formatter}
        onInserted={mention.directive.onInserted}
      />
      <ComposerPrimitive.Unstable_TriggerPopoverItems className="custom-scrollbar max-h-52 overflow-y-auto p-1.5">
        {(visibleItems) =>
          visibleItems.length > 0 ? (
            visibleItems.map((item, index) => {
              const Icon =
                item.type === SKILL_REFERENCE_DIRECTIVE_TYPE
                  ? FolderSymlink
                  : SquareCode;
              return (
                <ComposerPrimitive.Unstable_TriggerPopoverItem
                  key={`${item.type}:${item.id}`}
                  item={item}
                  index={index}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left outline-none hover:bg-accent data-[highlighted]:bg-accent"
                >
                  <Icon className="size-4 shrink-0 text-primary" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {item.label}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {item.description}
                    </span>
                  </span>
                </ComposerPrimitive.Unstable_TriggerPopoverItem>
              );
            })
          ) : (
            <div className="flex items-center gap-2 px-2.5 py-3 text-xs text-muted-foreground">
              <FileQuestion className="size-4" />
              {t("skillManagement.mentions.noFiles", {
                defaultValue: "No matching .md, .sh, or .py files",
              })}
            </div>
          )
        }
      </ComposerPrimitive.Unstable_TriggerPopoverItems>
    </ComposerPrimitive.Unstable_TriggerPopover>
  );
};
