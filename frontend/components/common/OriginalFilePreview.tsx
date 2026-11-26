// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Segmented, Spin } from "antd";
import { useTranslation } from "react-i18next";
import Papa from "papaparse";
import { MarkdownRenderer, extractMarkdownHeadings } from "./markdownRenderer";
import { columnIndexToLetters } from "@/lib/spreadsheetGrid";
import log from "@/lib/logger";
import PreviewControls from "./PreviewControls";
import styles from "./DocumentPreview.module.css";

export const ORIGINAL_READER_EXTENSIONS = new Set([
  "txt",
  "json",
  "md",
  "markdown",
  "html",
  "csv",
  "png",
  "jpg",
  "jpeg",
  "bmp",
]);

function htmlDocument(source: string, fontSize: number): string {
  const doc = new DOMParser().parseFromString(source, "text/html");
  doc
    .querySelectorAll("script,iframe,object,embed,base,link,meta,form")
    .forEach((node) => node.remove());
  doc.querySelectorAll("*").forEach((node) => {
    for (const attribute of Array.from(node.attributes)) {
      if (
        /^on/i.test(attribute.name) ||
        ["href", "srcset", "action", "formaction"].includes(attribute.name)
      )
        node.removeAttribute(attribute.name);
      if (
        attribute.name === "src" &&
        !attribute.value.startsWith("data:image/")
      )
        node.removeAttribute("src");
    }
  });
  const policy =
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'";
  return (
    '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="' +
    policy +
    '">' +
    doc.head.innerHTML +
    '<style>html{overflow-wrap:anywhere}body{box-sizing:border-box;font-family:"Microsoft YaHei",sans-serif;font-size:' +
    fontSize +
    "px;line-height:1.8;max-width:880px;width:auto;margin:0 auto;padding:32px}img,table{max-width:100%}</style></head><body>" +
    doc.body.innerHTML +
    "</body></html>"
  );
}

function JsonContent({ text }: { text: string }) {
  const parts = text.split(
    /("(?:\\.|[^"\\])*"\s*:|"(?:\\.|[^"\\])*"|\b(?:true|false|null|-?\d+(?:\.\d+)?)\b)/g
  );
  return (
    <>
      {parts.map((part, index) => (
        <span
          key={index}
          className={
            part.startsWith('"')
              ? part.trimEnd().endsWith(":")
                ? styles.codeKey
                : styles.codeString
              : /^(-?\d|true|false|null)/.test(part)
                ? styles.codeNumber
                : undefined
          }
        >
          {part}
        </span>
      ))}
    </>
  );
}

export default function OriginalFilePreview({
  fileName,
  loadOriginal,
}: {
  fileName: string;
  loadOriginal: () => Promise<Response>;
}) {
  const { t } = useTranslation();
  const extension = fileName.split(".").pop()?.toLowerCase() ?? "txt";
  const image = ["png", "jpg", "jpeg", "bmp"].includes(extension);
  const markdown = ["md", "markdown"].includes(extension);
  const [text, setText] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading"
  );
  const [attempt, setAttempt] = useState(0);
  const [mode, setMode] = useState("preview");
  const [zoom, setZoom] = useState(1);
  const [navigation, setNavigation] = useState(false);
  const [natural, setNatural] = useState({ width: 0, height: 0 });
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const imageRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    void loadOriginal()
      .then(async (response) => {
        const blob = await response.blob();
        if (cancelled) return;
        if (image) {
          objectUrl = URL.createObjectURL(blob);
          setImageUrl(objectUrl);
        } else {
          const value = await blob.text();
          if (cancelled) return;
          setText(value.replace(/^\uFEFF/, ""));
        }
        setStatus("ready");
      })
      .catch((error) => {
        if (!cancelled) {
          log.error("Failed to read original document", { fileName, error });
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [loadOriginal, fileName, image, attempt]);
  useEffect(() => {
    const node = imageRef.current;
    if (!node) return;
    const observer = new ResizeObserver(() =>
      setViewport({
        width: node.clientWidth - 48,
        height: node.clientHeight - 48,
      })
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [status, image]);
  const headings = useMemo(
    () => (markdown ? extractMarkdownHeadings(text) : []),
    [markdown, text]
  );
  const csv = useMemo(
    () =>
      extension === "csv"
        ? Papa.parse<string[]>(text, { skipEmptyLines: "greedy" }).data
        : [],
    [extension, text]
  );
  const json = useMemo(() => {
    if (extension !== "json") return text;
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return text;
    }
  }, [extension, text]);
  const html = useMemo(
    () =>
      extension === "html" && typeof document !== "undefined"
        ? htmlDocument(text, 14 * zoom)
        : "",
    [extension, text, zoom]
  );
  const fit =
    natural.width > 0 && viewport.width > 0
      ? Math.min(
          viewport.width / natural.width,
          viewport.height / natural.height,
          1
        )
      : 1;
  const [imageCustom, setImageCustom] = useState(false);
  const imageZoom = imageCustom ? zoom : fit;
  if (status === "loading")
    return (
      <div className="flex h-full items-center justify-center">
        <Spin />
      </div>
    );
  if (status === "error")
    return (
      <div className="p-6">
        <Alert
          type="error"
          title={t("filePreview.previewFailed")}
          action={
            <Button
              onClick={() => {
                setStatus("loading");
                setAttempt((value) => value + 1);
              }}
            >
              {t("common.retry")}
            </Button>
          }
        />
      </div>
    );
  const hasModes = markdown || ["html", "json", "csv"].includes(extension);
  return (
    <div className={styles.reader}>
      {hasModes && (
        <div className={styles.toolbar}>
          <span>{extension.toUpperCase()}</span>
          <Segmented
            size="small"
            value={mode}
            onChange={(value) => setMode(String(value))}
            options={[
              {
                value: "preview",
                label: t(
                  extension === "csv"
                    ? "filePreview.reader.table"
                    : "filePreview.reader.preview"
                ),
              },
              { value: "source", label: t("filePreview.reader.source") },
            ]}
          />
        </div>
      )}
      {image ? (
        <div ref={imageRef} className={styles.imageViewport}>
          <img
            src={imageUrl}
            alt={fileName}
            onLoad={(event) => {
              setNatural({
                width: event.currentTarget.naturalWidth,
                height: event.currentTarget.naturalHeight,
              });
              setImageCustom(false);
            }}
            style={
              natural.width
                ? {
                    width: natural.width * imageZoom,
                    height: natural.height * imageZoom,
                  }
                : { maxWidth: "100%", maxHeight: "100%" }
            }
          />
        </div>
      ) : extension === "html" && mode === "preview" ? (
        <iframe
          className={styles.html}
          title={fileName}
          sandbox=""
          referrerPolicy="no-referrer"
          srcDoc={html}
        />
      ) : extension === "csv" && mode === "preview" ? (
        <>
          <div className={styles.toolbar}>
            {t("filePreview.reader.rows", {
              rows: csv.length,
              columns: csv.reduce((max, row) => Math.max(max, row.length), 0),
            })}
          </div>
          <div className={styles.sheetViewport}>
            <table className={styles.grid} style={{ fontSize: 14 * zoom }}>
              <thead>
                <tr>
                  <th />
                  {Array.from(
                    {
                      length: Math.min(
                        40,
                        csv.reduce((max, row) => Math.max(max, row.length), 0)
                      ),
                    },
                    (_, index) => (
                      <th key={index}>{columnIndexToLetters(index)}</th>
                    )
                  )}
                </tr>
              </thead>
              <tbody>
                {csv.slice(0, 300).map((row, index) => (
                  <tr key={index}>
                    <td>{index + 1}</td>
                    {row.slice(0, 40).map((cell, column) => (
                      <td key={column}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(csv.length > 300 || csv.some((row) => row.length > 40)) && (
            <div className={styles.toolbar}>
              {t("filePreview.reader.truncated")}
            </div>
          )}
        </>
      ) : (
        <div className="flex min-h-0 min-w-0 flex-1">
          {markdown && navigation && mode === "preview" && (
            <nav
              className={styles.slideRail}
              aria-label={t("filePreview.pdf.outline")}
            >
              {headings.map((heading) => (
                <button
                  key={heading.id}
                  style={{ paddingLeft: 8 + (heading.level - 1) * 12 }}
                  onClick={() =>
                    contentRef.current
                      ?.querySelector('[id="' + heading.id + '"]')
                      ?.scrollIntoView({ block: "start" })
                  }
                >
                  {heading.text}
                </button>
              ))}
            </nav>
          )}
          <div ref={contentRef} className={styles.viewport}>
            <div className={styles.paper} style={{ fontSize: 14 * zoom }}>
              {markdown && mode === "preview" ? (
                <MarkdownRenderer
                  content={text}
                  enableMultimodal={false}
                  resolveS3Media={false}
                />
              ) : (
                <pre
                  className={`${styles.text} ${extension !== "txt" ? styles.code : ""}`}
                  style={{ fontSize: 14 * zoom }}
                >
                  {extension === "json" && mode === "preview" ? (
                    <JsonContent text={json} />
                  ) : (
                    text
                  )}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
      <PreviewControls
        zoom={image ? imageZoom : zoom}
        onZoom={(value) => {
          setZoom(value);
          setImageCustom(true);
        }}
        onFit={image ? () => setImageCustom(false) : () => setZoom(1)}
        onToggleNavigation={
          markdown && headings.length
            ? () => setNavigation((value) => !value)
            : undefined
        }
        navigationOpen={navigation}
      />
    </div>
  );
}
