"use client";

import { visit } from "unist-util-visit";
import type { Plugin } from "unified";
import type { Root, Text, InlineCode, PhrasingContent } from "mdast";
import type { Node } from "unist";

/**
 * Regex to match [[citekey]] markers in text.
 * Matches patterns like: [[b1]], [[a1]], [[1]], [[cite3]], etc.
 */
const CITE_REGEX = /\[\[([^\]]+)\]\]/g;
const CITE_SEQUENCE_REGEX = /^(?:\[\[[^\]]+\]\])+$/;

function createCiteNode(citekey: string): PhrasingContent {
  return {
    type: "cite",
    data: {
      citekey,
      hName: "cite",
      hProperties: { citekey },
    },
    children: [] as Text[],
  } as unknown as PhrasingContent;
}

/**
 * Remark plugin that transforms `[[citekey]]` text nodes into custom
 * `cite` nodes in the MDAST tree. This allows the markdown renderer to
 * replace them with interactive CiteMarker components.
 *
 * Example:
 *   Input:  "Some text [[b1]] more text"
 *   Output: [
 *     { type: "text", value: "Some text " },
 *     { type: "cite", data: { citekey: "b1" } },
 *     { type: "text", value: " more text" },
 *   ]
 */
export const remarkCite: Plugin<[], Root> = () => {
  return (tree: Root) => {
    visit(
      tree,
      "text",
      (node: Text, index: number | undefined, parent: Node | undefined) => {
        if (index === undefined || !parent) return;

        const text = node.value;
        if (!text.includes("[[")) return;

        const newNodes: PhrasingContent[] = [];
        let lastIndex = 0;
        let match: RegExpExecArray | null;

        CITE_REGEX.lastIndex = 0;

        while ((match = CITE_REGEX.exec(text)) !== null) {
          const matchStart = match.index;
          const matchEnd = matchStart + match[0].length;
          const citekey = match[1];

          if (matchStart > lastIndex) {
            newNodes.push({
              type: "text",
              value: text.slice(lastIndex, matchStart),
            });
          }

          newNodes.push(createCiteNode(citekey));
          lastIndex = matchEnd;
        }

        if (lastIndex < text.length) {
          newNodes.push({
            type: "text",
            value: text.slice(lastIndex),
          });
        }

        if (newNodes.length > 0) {
          (parent as { children?: PhrasingContent[] }).children?.splice(
            index,
            1,
            ...newNodes,
          );
          return [undefined, index + newNodes.length] as const;
        }
      },
    );

    visit(
      tree,
      "inlineCode",
      (node: InlineCode, index: number | undefined, parent: Node | undefined) => {
        if (index === undefined || !parent) return;

        const value = node.value.trim();
        if (!CITE_SEQUENCE_REGEX.test(value)) return;

        const citeNodes: PhrasingContent[] = [];
        CITE_REGEX.lastIndex = 0;
        let match: RegExpExecArray | null;
        while ((match = CITE_REGEX.exec(value)) !== null) {
          citeNodes.push(createCiteNode(match[1]));
        }

        (parent as { children?: PhrasingContent[] }).children?.splice(
          index,
          1,
          ...citeNodes,
        );
      },
    );
  };
};

/**
 * Type augmentation for the custom cite MDAST node.
 */
declare module "mdast" {
  interface PhrasingContentMap {
    cite: CiteNode;
  }
}

export interface CiteNode {
  type: "cite";
  data: {
    citekey: string;
    hName: "cite";
    hProperties: { citekey: string };
  };
  children: [];
}
