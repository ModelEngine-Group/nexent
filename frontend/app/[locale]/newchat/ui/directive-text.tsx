"use client";

import { memo, type FC } from "react";
import {
  unstable_defaultDirectiveFormatter,
  type Unstable_DirectiveSegment,
  type TextMessagePartComponent,
  type Unstable_DirectiveFormatter,
} from "@assistant-ui/react";

import {
  combinedSkillDirectiveFormatter,
  skillDirectiveIconMap,
} from "./skill-directives";

type IconComponent = FC<{ className?: string }>;

export type CreateDirectiveTextOptions = {
  // Maps a directive `type` to an icon component.
  iconMap?: Record<string, IconComponent>;
  // Icon rendered when `iconMap` has no entry for the segment type.
  fallbackIcon?: IconComponent;
};

export const DirectiveChip: FC<{
  segment: Extract<Unstable_DirectiveSegment, { kind: "mention" }>;
  iconMap?: Record<string, IconComponent>;
  fallbackIcon?: IconComponent;
  onClick?: (
    segment: Extract<Unstable_DirectiveSegment, { kind: "mention" }>
  ) => void;
}> = ({ segment, iconMap, fallbackIcon, onClick }) => {
  const Icon = iconMap?.[segment.type] ?? fallbackIcon;
  const content = (
    <>
      {Icon && <Icon className="size-3" />}
      {segment.label}
    </>
  );
  const className =
    "bg-muted text-foreground mx-0.5 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 align-middle text-xs font-medium";

  return onClick ? (
    <button
      type="button"
      data-slot="directive-chip"
      data-type={segment.type}
      title={segment.id}
      aria-label={`${segment.label}: ${segment.id}`}
      className={`${className} cursor-pointer hover:bg-muted/70`}
      onClick={() => onClick(segment)}
    >
      {content}
    </button>
  ) : (
    <span
      data-slot="directive-chip"
      data-type={segment.type}
      title={segment.id}
      aria-label={`${segment.label}: ${segment.id}`}
      className={className}
    >
      {content}
    </span>
  );
};

/**
 * Creates a `Text` message part component that parses directive syntax and
 * renders inline chips.
 */
export function createDirectiveText(
  formatter: Unstable_DirectiveFormatter,
  options?: CreateDirectiveTextOptions
): TextMessagePartComponent {
  const iconMap = options?.iconMap;
  const fallbackIcon = options?.fallbackIcon;

  const DirectiveText: TextMessagePartComponent = ({ text }) => {
    const segments = formatter.parse(text);

    if (segments.length === 1 && segments[0]?.kind === "text") {
      return <>{text}</>;
    }

    return (
      <>
        {segments.map((seg, i) => {
          if (seg.kind === "text") {
            return <span key={i}>{seg.text}</span>;
          }

          return (
            <DirectiveChip
              key={i}
              segment={seg}
              iconMap={iconMap}
              fallbackIcon={fallbackIcon}
            />
          );
        })}
      </>
    );
  };

  DirectiveText.displayName = "DirectiveText";
  return DirectiveText;
}

const DirectiveTextImpl = createDirectiveText(
  unstable_defaultDirectiveFormatter
);

/**
 * `Text` message part component that renders directive syntax as inline chips.
 */
export const DirectiveText: TextMessagePartComponent = memo(DirectiveTextImpl);

const SkillDirectiveTextImpl = createDirectiveText(
  combinedSkillDirectiveFormatter,
  { iconMap: skillDirectiveIconMap }
);

export const SkillDirectiveText: TextMessagePartComponent = memo(
  SkillDirectiveTextImpl
);
