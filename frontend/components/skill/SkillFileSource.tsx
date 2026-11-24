// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export function getSkillSourceLines(content: string) {
  return content.replace(/\r?\n$/, "").split(/\r?\n/);
}

export default function SkillFileSource({ content }: { content: string }) {
  const lines = getSkillSourceLines(content);
  return (
    <div className="flex w-max min-w-full py-2 font-mono text-body-1 leading-5 text-foreground">
      <pre
        aria-hidden="true"
        className="shrink-0 select-none px-3 text-right text-muted-foreground"
      >
        {content && lines.map((_, index) => index + 1).join("\n")}
      </pre>
      <pre className="pr-4">{lines.join("\n")}</pre>
    </div>
  );
}
