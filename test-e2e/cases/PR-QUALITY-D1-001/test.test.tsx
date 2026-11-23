vi.mock("@/app/i18n", () => ({ default: { t: (key: string) => key, language: "zh" } }));
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ParamSlider } from "@/components/resource-picker/ParamDialog";
import { useEmbeddingModelDialog } from "@/hooks/knowledge/useEmbeddingModelDialog";
import { KnowledgeModelMismatchModal } from "@/components/tool-config/KnowledgeModelMismatchModal";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }) }));
vi.mock("antd", () => ({
  Modal: ({ open, title, children, footer, onCancel }: any) => open ? <section role="dialog">{title}{children}{footer}<button onClick={onCancel}>close</button></section> : null,
  Button: ({ children, onClick }: any) => <button onClick={onClick}>{children}</button>,
  Input: () => null,
}));
afterEach(cleanup);

describe("[PR-QUALITY-D1-001] Accessible parameter input", () => {
  it("supports arrows, endpoints and bounds without reacting to unrelated keys", () => {
    const onChange = vi.fn();
    const { rerender } = render(<ParamSlider value={50} minLabel="0" maxLabel="100" onChange={onChange} />);
    const slider = screen.getByRole("slider");
    for (const [key, expected] of [["ArrowRight", 51], ["ArrowUp", 51], ["ArrowLeft", 49], ["ArrowDown", 49], ["Home", 0], ["End", 100]] as const) {
      fireEvent.keyDown(slider, { key });
      expect(onChange).toHaveBeenLastCalledWith(expected);
    }
    onChange.mockClear();
    fireEvent.keyDown(slider, { key: "a" });
    expect(onChange).not.toHaveBeenCalled();
    rerender(<ParamSlider value={100} minLabel="0" maxLabel="100" onChange={onChange} />);
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith(100);
    rerender(<ParamSlider value={0} minLabel="0" maxLabel="100" onChange={onChange} />);
    fireEvent.keyDown(slider, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith(0);
  });
  it("preserves proportional mouse selection and read-only behavior", () => {
    const onChange = vi.fn();
    const { rerender } = render(<ParamSlider value={20} minLabel="0" maxLabel="100" onChange={onChange} />);
    const slider = screen.getByRole("slider");
    vi.spyOn(slider, "getBoundingClientRect").mockReturnValue({ left: 10, width: 100 } as DOMRect);
    fireEvent.click(slider, { clientX: 60 });
    expect(onChange).toHaveBeenLastCalledWith(50);
    fireEvent.click(slider, { clientX: 150 });
    expect(onChange).toHaveBeenLastCalledWith(100);
    onChange.mockClear();
    rerender(<ParamSlider value={20} minLabel="0" maxLabel="100" />);
    expect(slider.getAttribute("aria-disabled")).toBe("true");
    expect(slider.tabIndex).toBe(-1);
    fireEvent.click(slider, { clientX: 60 });
    fireEvent.keyDown(slider, { key: "End" });
    expect(onChange).not.toHaveBeenCalled();
  });
});
