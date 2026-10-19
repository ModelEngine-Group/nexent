// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";

import { neutralizeUnsafeLinks, sanitizeOfficeHtml } from "@/lib/officePreview";

/** Parse untrusted markup the way the preview components do. */
function parseMarkup(html: string): HTMLElement {
  const container = document.createElement("div");
  container.innerHTML = html;
  return container;
}

describe("sanitizeOfficeHtml", () => {
  it("drops executable subtrees together with their text", () => {
    const html = sanitizeOfficeHtml(
      "<p>kept</p><script>alert(1)</script>" +
        '<iframe src="https://tracker.test/pixel"></iframe>'
    );

    expect(html).toContain("kept");
    expect(html).not.toContain("alert(1)");
    expect(html).not.toContain("iframe");
    expect(html).not.toContain("tracker.test");
  });

  it("unwraps unknown elements, losing their attributes but keeping the text", () => {
    const html = sanitizeOfficeHtml(
      '<section><a href="javascript:alert(1)">link text</a></section>'
    );

    expect(html).toBe("link text");
  });

  it("keeps allowed elements with the inline styles the layout relies on", () => {
    const html = sanitizeOfficeHtml(
      '<p style="font-size: 18pt; color: #ff0000">title</p>'
    );

    expect(html).toBe('<p style="font-size: 18pt; color: #ff0000">title</p>');
  });

  it("drops every attribute other than the filtered style", () => {
    const html = sanitizeOfficeHtml(
      '<p id="a" class="b" onclick="alert(1)" style="color: red">x</p>'
    );

    expect(html).toBe('<p style="color: red">x</p>');
  });

  it("drops style declarations that load remote content or run code", () => {
    const html = sanitizeOfficeHtml(
      "<p" +
        ' style="color: red; background-image: url(https://tracker.test/p.png);' +
        " font-family: expression(alert(1)); font-size: 12pt; width: 100%" +
        '">x</p>'
    );

    expect(html).toContain("color: red");
    expect(html).toContain("font-size: 12pt");
    expect(html).not.toContain("url(");
    expect(html).not.toContain("expression(");
    expect(html).not.toContain("width");
  });

  it("drops style values that use a CSS escape to spell a scheme", () => {
    const html = sanitizeOfficeHtml(
      '<p style="font-family: \\6a avascript">x</p>'
    );

    expect(html).toBe("<p>x</p>");
  });

  it("returns an empty string for markup that is not a string", () => {
    expect(sanitizeOfficeHtml("")).toBe("");
  });
});

describe("neutralizeUnsafeLinks", () => {
  const unsafeTargets = [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    // A scheme written as a character reference is decoded by the parser, so
    // the check has to happen after rendering.
    "&#106;avascript:alert(1)",
    // Browsers ignore the tab while parsing the URL.
    "java\tscript:alert(1)",
    "vbscript:msgbox(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
  ];

  it.each(unsafeTargets)("removes the %s target", (target) => {
    const container = parseMarkup(`<a href="${target}">link text</a>`);

    neutralizeUnsafeLinks(container);

    const link = container.querySelector("a");
    expect(link).not.toBeNull();
    // Only the navigation goes away: the text stays readable.
    expect(link?.hasAttribute("href")).toBe(false);
    expect(link?.textContent).toBe("link text");
  });

  const safeTargets = [
    "https://example.test/report.pdf",
    "mailto:someone@example.test",
    "#section-2",
    "images/logo.png",
    "/absolute/path",
  ];

  it.each(safeTargets)("keeps the %s target", (target) => {
    const container = parseMarkup(`<a href="${target}">link text</a>`);

    neutralizeUnsafeLinks(container);

    expect(container.querySelector("a")?.getAttribute("href")).toBe(target);
  });

  it("leaves links that carry no target alone", () => {
    const container = parseMarkup("<a>link text</a>");

    neutralizeUnsafeLinks(container);

    expect(container.querySelector("a")?.hasAttribute("href")).toBe(false);
  });
});
