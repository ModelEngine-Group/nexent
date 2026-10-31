// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  escapeCurrencyDollars,
  normalizeMathDelimiters,
} from "@assistant-ui/react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Root } from "mdast";
import type { PluggableList, Plugin } from "unified";
import { visit } from "unist-util-visit";

// remark-math treats single-line $$...$$ as inline math. Model answers also
// use that common display form, including several formulas on the same line.
const remarkDisplayMath: Plugin<[], Root> = () => (tree, file) => {
  const source = String(file);
  visit(tree, "inlineMath", (node) => {
    const offset = node.position?.start.offset;
    if (offset !== undefined && source.startsWith("$$", offset) && node.data) {
      node.data.hProperties = {
        ...node.data.hProperties,
        className: ["language-math", "math-display"],
      };
    }
  });
};

// Share syntax support across answer, streaming reasoning and saved reasoning.
export const chatRemarkPlugins: PluggableList = [
  remarkGfm,
  remarkMath,
  remarkDisplayMath,
];
export const chatRehypePlugins: PluggableList = [
  [rehypeKatex, { throwOnError: false, strict: false, trust: false }],
];

export const preprocessChatMarkdown = (text: string): string =>
  escapeCurrencyDollars(normalizeMathDelimiters(text));
