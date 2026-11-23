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

describe("[PR-QUALITY-D1-002] Preserved knowledge dialog lifecycle", () => {
  it("keeps knowledge configuration props and resets transient state on close", () => {
    const { result } = renderHook(useEmbeddingModelDialog);
    act(() => {
      result.current.setEmbeddingModelDialogOpen(true);
      result.current.setEmbeddingModelDialogData({ indexName: "kb-a", knowledgeName: "Knowledge A" });
      result.current.setEmbeddingModelDialogMismatch(true);
      result.current.setConfiguringKbIds(new Set(["kb-a", "kb-b"]));
    });
    expect(result.current.embeddingModelDialogProps).toMatchObject({ isOpen: true, indexName: "kb-a", knowledgeBaseName: "Knowledge A", isModelMismatch: true, kbIdsToUpdate: ["kb-a", "kb-b"] });
    act(() => result.current.embeddingModelDialogProps.onClose());
    expect(result.current.embeddingModelDialogProps).toMatchObject({ isOpen: false, indexName: "", knowledgeBaseName: "", isModelMismatch: false, kbIdsToUpdate: [] });
    act(() => result.current.setEmbeddingModelDialogOpen(true));
    expect(result.current.configuringKbIds.size).toBe(0);
  });
  it("keeps warning content and isolated cancel/confirm callbacks", () => {
    const onCancel = vi.fn(), onConfirm = vi.fn();
    render(<KnowledgeModelMismatchModal open info={{ existingModel: "Model A", newModel: "Model B", existingKBName: "Knowledge A", newKBName: "Knowledge B" }} onCancel={onCancel} onConfirm={onConfirm} />);
    expect(screen.getByText("Knowledge A")).toBeTruthy();
    expect(screen.getByText("Knowledge B")).toBeTruthy();
    fireEvent.click(screen.getByText("common.cancel"));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("切换模型"));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
