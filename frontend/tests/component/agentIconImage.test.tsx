// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, describe, expect, it, vi } from "vitest";
import { createAgentIconFile } from "../../lib/chat/agentIconImage";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function mockCanvas(mode: string) {
  const createElement = document.createElement.bind(document);
  const canvas = createElement("canvas");
  const context = {
    fillStyle: "",
    fillRect: vi.fn(),
    drawImage: vi.fn(() => {
      if (mode === "draw-failed") throw new Error("drawing failed");
    }),
  };
  vi.spyOn(document, "createElement").mockImplementation(((
    tag: string,
    options?: ElementCreationOptions
  ) =>
    tag === "canvas"
      ? canvas
      : createElement(tag, options)) as typeof document.createElement);
  vi.spyOn(canvas, "getContext").mockReturnValue(
    mode === "no-context"
      ? null
      : (context as unknown as CanvasRenderingContext2D)
  );
  vi.spyOn(canvas, "toBlob").mockImplementation((callback) =>
    callback(
      mode === "no-blob" ? null : new Blob(["png"], { type: "image/png" })
    )
  );
  vi.stubGlobal(
    "Image",
    class {
      async decode() {
        if (mode === "decode-failed") throw new Error("decoding failed");
      }
    }
  );
  const revoke = vi.fn();
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn(() => "blob:avatar-test"),
    revokeObjectURL: revoke,
  });
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("stroke", "currentColor");
  return { svg, canvas, context, revoke };
}

describe("createAgentIconFile", () => {
  it("produces a PNG without mutating the displayed SVG and releases its temporary URL", async () => {
    const { svg, canvas, context, revoke } = mockCanvas("success");
    const file = await createAgentIconFile(svg);
    expect(file.name).toBe("agent-icon.png");
    expect(file.type).toBe("image/png");
    expect(file.size).toBeGreaterThan(0);
    expect(canvas.width).toBe(200);
    expect(canvas.height).toBe(200);
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(context.drawImage).toHaveBeenCalledWith(
      expect.anything(),
      52,
      52,
      96,
      96
    );
    expect(revoke).toHaveBeenCalledWith("blob:avatar-test");
  });

  it.each(["no-context", "decode-failed", "no-blob", "draw-failed"])(
    "rejects %s and cleans up resources",
    async (mode) => {
      const { svg, revoke } = mockCanvas(mode);
      await expect(createAgentIconFile(svg)).rejects.toThrow();
      if (mode === "no-context") expect(revoke).not.toHaveBeenCalled();
      else expect(revoke).toHaveBeenCalledWith("blob:avatar-test");
    }
  );
});
