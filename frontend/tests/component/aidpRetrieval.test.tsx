// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useState } from "react";
import policyFixtures from "../../../test/fixtures/aidp_retrieval_config.json";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AidpRetrievalParamsForm } from "@/components/tool-config/AidpRetrievalParamsForm";
import { AidpRetrievalDialog } from "@/components/tool-config/AidpRetrievalDialog";
import {
  aidpDefaults,
  aidpErrors,
  mergeAidpConfig,
  resolveAidpConfig,
} from "@/lib/aidpRetrievalConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (s: string) => s }),
}));

function Controlled({ initial = {} }: { initial?: Record<string, unknown> }) {
  const [values, setValues] = useState(initial);
  return (
    <>
      <AidpRetrievalParamsForm
        values={values}
        onChange={(patch) => setValues((current) => ({ ...current, ...patch }))}
      />
      <output data-testid="config">{JSON.stringify(values)}</output>
    </>
  );
}
const field = (name: string) =>
  screen.getByRole("spinbutton", { name: `aidpRetrieval.fields.${name}` });
const change = (name: string, value: string) =>
  fireEvent.change(field(name), { target: { value } });

describe("AIDP retrieval policy and controlled form", () => {
  it("reflects single-channel values when a tool configuration finishes loading", () => {
    const update = vi.fn();
    const view = render(
      <AidpRetrievalParamsForm values={{}} onChange={update} />
    );
    view.rerender(
      <AidpRetrievalParamsForm
        values={{ search_method: "graph_search" }}
        onChange={update}
      />
    );
    expect(
      screen.queryByText(/aidpRetrieval.combination/)
    ).not.toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("aidpRetrieval.details"));
    expect(
      screen.queryByRole("spinbutton", {
        name: "aidpRetrieval.fields.vector_candidates",
      })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("spinbutton", {
        name: "aidpRetrieval.fields.graph_top_k",
      })
    ).toHaveValue("0");
  });
  it.each(policyFixtures)("shares Python policy fixtures: $name", (fixture) => {
    expect(resolveAidpConfig(fixture.config)).toMatchObject(fixture.expected);
    expect(aidpErrors(fixture.config)).toEqual({});
  });
  it("preserves explicit values, null inheritance clearing and candidate following", () => {
    const saved = {
      top_k: 10,
      vector_candidates: 30,
      multi_modal: false,
      reranking_enable: false,
    };
    expect(
      resolveAidpConfig(mergeAidpConfig(saved, { top_k: 7 })).vector_candidates
    ).toBe(30);
    const c = resolveAidpConfig(
      mergeAidpConfig(saved, {
        top_k: 7,
        vector_candidates: null,
        multi_modal: null,
      })
    );
    expect(c.vector_candidates).toBe(7);
    expect(c.full_text_candidates).toBe(7);
    expect(c.multi_modal).toBe(false);
    expect(c.graph_reranking_enable).toBe(false);
    expect(saved.vector_candidates).toBe(30);
  });
  it("checks numeric ranges and positive quota relations in fusion as well", () => {
    for (const config of [
      { top_k: 0 },
      { top_k: true },
      { vector_candidates: 501 },
      { full_text_candidates: 0 },
      { graph_score_threshold: NaN },
      { hybrid_top_k: 8, graph_top_k: 5 },
      { hybrid_top_k: 6, full_text_candidates: 5 },
      { reranking_enable: false, graph_reranking_enable: true },
      { search_method: "vector_search|" },
    ])
      expect(Object.keys(aidpErrors(config)).length).toBeGreaterThan(0);
    expect(
      aidpErrors({
        ...aidpDefaults,
        hybrid_top_k: 0,
        graph_top_k: 0,
        reranking_mode: "jargon_coverage",
      })
    ).toEqual({});
  });
  it("starts collapsed, follows until manually set and restores following", () => {
    render(<Controlled />);
    expect(
      screen.queryByRole("spinbutton", {
        name: "aidpRetrieval.fields.vector_candidates",
      })
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("aidpRetrieval.details"));
    change("top_k", "30");
    expect(field("vector_candidates")).toHaveValue("30");
    change("vector_candidates", "50");
    change("top_k", "40");
    expect(field("vector_candidates")).toHaveValue("50");
    expect(field("full_text_candidates")).toHaveValue("40");
    fireEvent.click(screen.getAllByText("aidpRetrieval.follow")[0]);
    expect(field("vector_candidates")).toHaveValue("40");
    expect(
      JSON.parse(screen.getByTestId("config").textContent!).vector_candidates
    ).toBeNull();
  });
  it("disables graph reranking atomically with the global switch", () => {
    render(<Controlled />);
    fireEvent.click(
      screen.getByRole("switch", {
        name: "aidpRetrieval.fields.reranking_enable",
      })
    );
    fireEvent.click(screen.getByText("aidpRetrieval.details"));
    expect(
      screen.getByRole("switch", {
        name: "aidpRetrieval.fields.graph_reranking_enable",
      })
    ).toBeDisabled();
    expect(JSON.parse(screen.getByTestId("config").textContent!)).toEqual({
      reranking_enable: false,
      graph_reranking_enable: false,
    });
  });
  it("keeps a single selected hybrid channel invalid and does not auto-select", () => {
    render(<Controlled />);
    fireEvent.click(screen.getByText(/aidpRetrieval.combination/));
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "aidpRetrieval.methods.graph_search",
      })
    );
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "aidpRetrieval.methods.full_text_search",
      })
    );
    expect(
      screen.getByRole("checkbox", {
        name: "aidpRetrieval.methods.vector_search",
      })
    ).toBeChecked();
    const raw = JSON.parse(screen.getByTestId("config").textContent!);
    expect(aidpErrors(raw).search_method).toBe("method");
  });
  it("isolates cancel and confirms an atomic patch; reopen resets collapsed groups", () => {
    const confirm = vi.fn(),
      cancel = vi.fn(),
      saved = { top_k: 7 };
    const { unmount } = render(
      <AidpRetrievalDialog
        values={saved}
        onCancel={cancel}
        onConfirm={confirm}
      />
    );
    change("top_k", "40");
    fireEvent.click(screen.getByText("common.cancel"));
    expect(cancel).toHaveBeenCalledOnce();
    expect(confirm).not.toHaveBeenCalled();
    expect(saved).toEqual({ top_k: 7 });
    unmount();
    render(
      <AidpRetrievalDialog
        values={saved}
        onCancel={cancel}
        onConfirm={confirm}
      />
    );
    expect(field("top_k")).toHaveValue("7");
    expect(
      screen.queryByRole("spinbutton", {
        name: "aidpRetrieval.fields.vector_candidates",
      })
    ).not.toBeInTheDocument();
    change("top_k", "30");
    fireEvent.click(
      within(screen.getByRole("dialog")).getByText("common.confirm")
    );
    expect(confirm).toHaveBeenCalledWith({ top_k: 30 });
  });
});
