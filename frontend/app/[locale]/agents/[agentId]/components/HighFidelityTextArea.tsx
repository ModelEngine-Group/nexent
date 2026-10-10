"use client";

import { forwardRef, type ChangeEventHandler } from "react";
import { Input } from "antd";
import type { TextAreaProps, TextAreaRef } from "antd/es/input/TextArea";

interface HighFidelityTextAreaProps extends Omit<
  TextAreaProps,
  "maxLength" | "showCount" | "onChange" | "value"
> {
  limit: number;
  value?: string;
  onChange?: ChangeEventHandler<HTMLTextAreaElement>;
}

const HighFidelityTextArea = forwardRef<TextAreaRef, HighFidelityTextAreaProps>(
  function HighFidelityTextArea(
    { limit, value = "", onChange, ...props },
    ref
  ) {
    return (
      <Input.TextArea
        {...props}
        ref={ref}
        value={value}
        maxLength={value.length > limit ? undefined : limit}
        showCount={{ formatter: ({ count }) => `${count}/${limit}` }}
        onChange={(event) => {
          const nextLength = event.target.value.length;
          // Existing oversized values remain editable without silently truncating them.
          if (nextLength <= limit || nextLength <= value.length)
            onChange?.(event);
        }}
      />
    );
  }
);

export default HighFidelityTextArea;
