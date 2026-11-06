// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Convert a rendered legacy icon into a PNG accepted by the existing upload API. */
export async function createAgentIconFile(svg: SVGSVGElement): Promise<File> {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 200;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas is unavailable");

  const icon = svg.cloneNode(true) as SVGSVGElement;
  icon.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  icon.setAttribute("width", "112");
  icon.setAttribute("height", "112");
  icon.setAttribute("stroke", "#0067d1");
  icon.setAttribute("color", "#0067d1");
  icon.removeAttribute("class");

  const source = new Blob([new XMLSerializer().serializeToString(icon)], {
    type: "image/svg+xml;charset=utf-8",
  });
  const url = URL.createObjectURL(source);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    context.fillStyle = "#e6f2fd";
    context.fillRect(0, 0, 200, 200);
    context.drawImage(image, 44, 44, 112, 112);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/png")
    );
    if (!blob) throw new Error("Failed to encode the agent icon");
    return new File([blob], "agent-icon.png", { type: "image/png" });
  } finally {
    URL.revokeObjectURL(url);
  }
}
