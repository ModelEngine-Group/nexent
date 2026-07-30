"use client";

import React from "react";

interface OfficialBadgeProps {
  text?: string;
  className?: string;
}

/**
 * OfficialBadge - Official content badge
 * Purple background with white dot + "Official" text
 */
export function OfficialBadge({ text = "Official", className = "" }: OfficialBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 rounded-full text-[10px] font-medium text-white bg-[#534AB7] ${className}`}
      style={{ height: "18px" }}
    >
      <span className="w-1 h-1 rounded-full bg-white" />
      {text}
    </span>
  );
}

export default OfficialBadge;
