"use client";

import { memo, type FC } from "react";
import {
  unstable_defaultDirectiveFormatter,
  type TextMessagePartComponent,
  type Unstable_DirectiveFormatter,
} from "@assistant-ui/react";

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

          const Icon = iconMap?.[seg.type] ?? fallbackIcon;
          return (
            <span
              key={i}
              data-slot="directive-chip"
              data-type={seg.type}
              className="bg-muted text-foreground mx-0.5 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 align-middle text-xs font-medium"
            >
              {Icon && <Icon className="size-3" />}
              {seg.label}
            </span>
          );
        })}
      </>
    );
  };

  DirectiveText.displayName = "DirectiveText";
  return DirectiveText;
}

const DirectiveTextImpl = createDirectiveText(unstable_defaultDirectiveFormatter);

/**
 * `Text` message part component that renders directive syntax as inline chips.
 */
export const DirectiveText: TextMessagePartComponent = memo(DirectiveTextImpl);
