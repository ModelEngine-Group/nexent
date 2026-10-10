import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AidpGroupNamesDisplay from "@/ext_components/aidp/components/AidpGroupNamesDisplay";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string | number>) =>
      options ? `${key} ${Object.values(options).join(" ")}` : key,
  }),
}));

describe("AIDP accessible user group display", () => {
  it("keeps a single row and opens the complete scrollable group list from +N", async () => {
    const groups = ["Default Group", "Operations", "Product", "Support"];
    const user = userEvent.setup();

    render(<AidpGroupNamesDisplay groupNames={groups} />);

    const summary = screen.getByTestId("aidp-group-names");
    expect(summary).toHaveClass("flex-nowrap");
    expect(screen.getByText("Default Group")).toBeInTheDocument();
    expect(screen.getByText("Operations")).toBeInTheDocument();
    expect(screen.queryByText("Product")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /\+2/ }));

    for (const group of groups) {
      expect(await screen.findAllByText(group)).not.toHaveLength(0);
    }
    expect(document.querySelector(".max-h-60.overflow-y-auto")).toBeTruthy();
  });
});
