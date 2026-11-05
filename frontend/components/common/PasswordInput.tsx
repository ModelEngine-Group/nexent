// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { forwardRef, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  InputField,
  type InputFieldProps,
} from "@/components/common/InputField";

/** Password visibility is local; the value and native input events remain caller-owned. */
export const PasswordInput = forwardRef<
  HTMLInputElement,
  Omit<InputFieldProps, "type" | "suffix">
>(function PasswordInput(props, ref) {
  const [visible, setVisible] = useState(false);
  const { t } = useTranslation("common");
  return (
    <InputField
      {...props}
      ref={ref}
      type={visible ? "text" : "password"}
      suffix={
        <button
          type="button"
          disabled={props.disabled}
          aria-label={t("common.togglePasswordVisibility")}
          aria-pressed={visible}
          className="rounded-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => setVisible(!visible)}
        >
          {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      }
    />
  );
});
