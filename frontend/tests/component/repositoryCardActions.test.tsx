// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import RepositoryCardActions from "@/app/resource-space/components/RepositoryCardActions";

test("renders two accessible icon actions and does not open card details", () => {
  const create = vi.fn();
  const takeDown = vi.fn();
  const detail = vi.fn();
  render(
    <div onClick={detail}>
      <RepositoryCardActions
        primary={{ label: "Create from template", onClick: create }}
        takeDown={{ label: "Take down", onClick: takeDown }}
      />
    </div>
  );
  const createButton = screen.getByRole("button", {
    name: "Create from template",
  });
  const takeDownButton = screen.getByRole("button", { name: "Take down" });
  expect(createButton.textContent).toBe("");
  expect(takeDownButton.textContent).toBe("");
  fireEvent.click(createButton);
  expect(create).toHaveBeenCalledTimes(1);
  expect(takeDown).not.toHaveBeenCalled();
  fireEvent.click(takeDownButton);
  expect(takeDown).toHaveBeenCalledTimes(1);
  expect(detail).not.toHaveBeenCalled();
});

test("does not expose a take-down action without permission", () => {
  render(
    <RepositoryCardActions primary={{ label: "Install", onClick: vi.fn() }} />
  );
  expect(screen.getAllByRole("button")).toHaveLength(1);
});

test("keeps take-down available when the installed primary action is hidden", () => {
  render(
    <RepositoryCardActions
      takeDown={{ label: "Take down", onClick: vi.fn() }}
    />
  );
  expect(screen.getAllByRole("button")).toHaveLength(1);
  expect(screen.getByRole("button", { name: "Take down" })).toBeTruthy();
});

test("renders nothing when installed and unable to take down", () => {
  const { container } = render(<RepositoryCardActions />);
  expect(container).toBeEmptyDOMElement();
});

test("prevents repeat requests while take-down is pending", () => {
  const takeDown = vi.fn();
  render(
    <RepositoryCardActions
      takeDown={{ label: "Take down", onClick: takeDown, loading: true }}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Take down" }));
  expect(takeDown).not.toHaveBeenCalled();
});

test("disables the primary action when availability is unknown", () => {
  const install = vi.fn();
  render(
    <RepositoryCardActions
      primary={{
        label: "Install",
        onClick: install,
        disabled: true,
        hint: "Unknown source",
      }}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Install" }));
  expect(install).not.toHaveBeenCalled();
});
