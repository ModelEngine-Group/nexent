// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const MARKDOWN_PLUGINS = [remarkGfm];

export function TrajectoryMarkdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={MARKDOWN_PLUGINS}
      skipHtml
      disallowedElements={["img"]}
    >
      {text}
    </ReactMarkdown>
  );
}
