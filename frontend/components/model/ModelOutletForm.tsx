// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";
import { ConfigProvider, Form, type FormProps } from "antd";

/** Match the project's 28px input contract without changing other model editors. */
export function ModelOutletForm(
  props: Omit<FormProps, "children"> & { children?: ReactNode }
) {
  return (
    <ConfigProvider theme={{ token: { controlHeight: 28, borderRadius: 4 } }}>
      <Form {...props} />
    </ConfigProvider>
  );
}
