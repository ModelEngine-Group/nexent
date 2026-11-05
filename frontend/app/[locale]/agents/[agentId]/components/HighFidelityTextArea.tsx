// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { forwardRef, type ChangeEventHandler } from "react";
import { Textarea, type TextareaProps } from "@/components/common/Textarea";

interface HighFidelityTextAreaProps extends Omit<
  TextareaProps,
  "maxLength" | "showCount" | "onChange" | "value"
> {
  limit: number;
  value?: string;
  onChange?: ChangeEventHandler<HTMLTextAreaElement>;
}

const HighFidelityTextArea = forwardRef<
  HTMLTextAreaElement,
  HighFidelityTextAreaProps
>(function HighFidelityTextArea(
  { limit, value = "", onChange, ...props },
  ref
) {
  return (
    <Textarea
      {...props}
      ref={ref}
      value={value}
      maxLength={value.length > limit ? undefined : limit}
      showCount
      countLimit={limit}
      onChange={(event) => {
        const nextLength = event.target.value.length;
        // Existing oversized values remain editable without silently truncating them.
        if (nextLength <= limit || nextLength <= value.length)
          onChange?.(event);
      }}
    />
  );
});

export default HighFidelityTextArea;
