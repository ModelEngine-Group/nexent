// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { memo } from "react";
import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  SourcesPanelProvider,
  useSourcesPanelActions,
  type SourcesPanelContextValue,
} from "@/app/newchat/ui/sources-panel-context";

it("keeps action consumers stable while selection changes and propagates changed actions", () => {
  const renders = vi.fn();
  const open = vi.fn(),
    toggle = vi.fn(),
    close = vi.fn();
  const Probe = memo(function Probe() {
    renders(useSourcesPanelActions().open);
    return null;
  });
  const initial: SourcesPanelContextValue = {
    selection: null,
    isOpen: false,
    open,
    toggle,
    close,
  };
  const view = render(
    <SourcesPanelProvider value={initial}>
      <Probe />
    </SourcesPanelProvider>
  );
  view.rerender(
    <SourcesPanelProvider
      value={{
        ...initial,
        isOpen: true,
        selection: {
          messageId: "one",
          groupId: "citations",
          sources: [],
          images: [],
        },
      }}
    >
      <Probe />
    </SourcesPanelProvider>
  );
  expect(renders).toHaveBeenCalledTimes(1);
  const nextOpen = vi.fn();
  view.rerender(
    <SourcesPanelProvider value={{ ...initial, open: nextOpen }}>
      <Probe />
    </SourcesPanelProvider>
  );
  expect(renders).toHaveBeenCalledTimes(2);
  expect(renders).toHaveBeenLastCalledWith(nextOpen);
});
