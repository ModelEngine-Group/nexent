// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Button, ConfigProvider } from "antd";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NEXENT_THEME } from "@/const/brand";

describe("shared modal and theme", () => {
  it("does not insert spaces into localized CJK button labels", () => {
    render(
      <ConfigProvider theme={NEXENT_THEME} button={{ autoInsertSpace: false }}>
        <Button>关闭</Button>
      </ConfigProvider>
    );
    expect(screen.getByRole("button", { name: "关闭" }).textContent).toBe(
      "关闭"
    );
  });
});
