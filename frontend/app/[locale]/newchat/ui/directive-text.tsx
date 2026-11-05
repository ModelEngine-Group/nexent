// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { memo, type FC } from "react";
import { DirectiveChip } from "@/components/common/markdown/DirectiveChip";
import {
  unstable_defaultDirectiveFormatter,
  type Unstable_DirectiveSegment,
  type TextMessagePartComponent,
  type Unstable_DirectiveFormatter,
} from "@assistant-ui/react";

import {
  combinedSkillDirectiveFormatter,
  skillDirectiveIconMap,
} from "@/lib/skillDirectives";

type IconComponent = FC<{ className?: string }>;

export type CreateDirectiveTextOptions = {
  // Maps a directive `type` to an icon component.
  iconMap?: Record<string, IconComponent>;
  // Icon rendered when `iconMap` has no entry for the segment type.
  fallbackIcon?: IconComponent;
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
