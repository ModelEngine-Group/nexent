import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResourceCard } from "@/features/workbench/components/ResourceCard";

describe("ResourceCard", () => {
  it.each(["Agent", "Skill", "知识库"])(
    "UT-FE-WB-016 renders the shared %s structure",
    (title) => {
      render(
        <ResourceCard
          title={title}
          description="Description"
          icon="icon"
          subtitle="Subtitle"
          tags={["Finance"]}
          badges={["READ"]}
          footer="Select"
        />
      );
      const card = screen.getByRole("option");
      for (const text of [
        title,
        "Description",
        "icon",
        "Subtitle",
        "Finance",
        "READ",
        "Select",
      ])
        expect(card.parentElement).toHaveTextContent(text);
      expect(card).toHaveAccessibleName(title);
    }
  );
  it("UT-FE-WB-017 unavailable cards expose a reason and reject selection", async () => {
    const select = vi.fn();
    render(
      <ResourceCard
        title="Unavailable"
        disabled
        disabledReason="Missing dependency"
        onClick={select}
      />
    );
    const card = screen.getByRole("option");
    expect(card).toBeDisabled();
    expect(card).toHaveAccessibleDescription("Missing dependency");
    await userEvent.click(card);
    expect(select).not.toHaveBeenCalled();
  });
  it("UT-FE-WB-018 supports Enter and Space with accessible selection", async () => {
    const select = vi.fn();
    render(<ResourceCard title="Agent" selected onClick={select} />);
    await userEvent.tab();
    const card = screen.getByRole("option");
    expect(card).toHaveFocus();
    await userEvent.keyboard("{Enter} ");
    expect(select).toHaveBeenCalledTimes(2);
    expect(card).toHaveAttribute("aria-selected", "true");
  });
  it("UT-FE-WB-037 deduplicates tags, exposes overflow and separates badges", () => {
    render(
      <ResourceCard
        title="Agent"
        tags={["A", "A", "B", "C", "D"]}
        badges={["READ"]}
      />
    );
    const tags = screen.getByLabelText("标签");
    expect(tags).not.toHaveTextContent("READ");
    expect(screen.getAllByText("A")).toHaveLength(1);
    expect(screen.getByText("+1")).toHaveAccessibleName("A、B、C、D");
    expect(screen.getByLabelText("资源状态")).toHaveTextContent("READ");
  });

  it.each(["编辑", "安装并选择"])(
    "keeps the %s action at the bottom-right of a compact Skill card",
    async (label) => {
      const select = vi.fn();
      const action = vi.fn();
      render(
        <ResourceCard
          resourceType="skill"
          title="workbench-smoke-date"
          description="将 YYYY-MM-DD 格式的日期字符串转换为中文日期格式。用户需要将标准日期格式转换为中文日期格式。"
          tags={["date", "text-processing", "chinese"]}
          badges={["repository"]}
          onClick={select}
          actions={
            <button type="button" onClick={action}>
              {label}
            </button>
          }
        />
      );

      const card = screen.getByRole("option").parentElement;
      const actionButton = screen.getByRole("button", { name: label });
      expect(card).toHaveClass("h-[220px]");
      expect(screen.getByText(/将 YYYY-MM-DD/)).toHaveStyle({
        WebkitLineClamp: 2,
      });
      expect(actionButton.parentElement).toHaveClass("justify-end");
      await userEvent.click(actionButton);
      expect(action).toHaveBeenCalledOnce();
      expect(select).not.toHaveBeenCalled();
    }
  );
});
