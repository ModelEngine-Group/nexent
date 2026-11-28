// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Blob as NodeBlob } from "node:buffer";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  ReadAloudButton,
  ReadAloudProvider,
} from "@/app/newchat/assistant-ui/read-aloud";
import { TooltipProvider } from "@/components/ui/tooltip";

const state = vi.hoisted(() => ({
  modelName: "qwen3-tts-flash-realtime",
  message: { id: "reply-1", content: [] as object[] },
  reportError: vi.fn(),
}));

vi.mock("@assistant-ui/react", () => ({
  useAuiState: (select: (value: typeof state) => unknown) => select(state),
}));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ modelConfig: { tts: { modelName: state.modelName } } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("antd", () => ({ message: { error: state.reportError } }));

const sockets: TestSocket[] = [];
class TestSocket {
  binaryType = "";
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn();

  constructor(readonly url: string) {
    sockets.push(this);
  }
}

const decoded = {} as AudioBuffer;
const player = {
  resume: vi.fn().mockResolvedValue(undefined),
  close: vi.fn().mockResolvedValue(undefined),
  decodeAudioData: vi.fn().mockResolvedValue(decoded),
  start: vi.fn(),
  end: null as (() => void) | null,
};

function reply() {
  return (
    <TooltipProvider>
      <ReadAloudProvider>
        <ReadAloudButton />
      </ReadAloudProvider>
    </TooltipProvider>
  );
}

const renderReply = () => render(reply());

const read = () =>
  screen.getByRole("button", { name: "chat.thread.readAloud" });
const stop = () =>
  screen.getByRole("button", { name: "chat.thread.stopReadAloud" });

beforeEach(() => {
  sockets.length = 0;
  player.end = null;
  state.modelName = "qwen3-tts-flash-realtime";
  state.message.content = [
    { type: "reasoning", text: "private reasoning" },
    { type: "text", text: "第一句。" },
    { type: "text", text: "tool warning", isWarning: true },
    { type: "text", text: "subagent output", metadata: { subagentId: 1 } },
    { type: "text", text: "第二句。" },
  ];
  vi.stubGlobal("WebSocket", TestSocket);
  vi.stubGlobal("Blob", NodeBlob);
  vi.stubGlobal(
    "AudioContext",
    class {
      destination = {};
      resume = player.resume;
      close = player.close;
      decodeAudioData = player.decodeAudioData;
      createBufferSource() {
        return {
          connect: vi.fn(),
          start: player.start,
          set onended(callback: () => void) {
            player.end = callback;
          },
        };
      }
    }
  );
});

afterEach(() => vi.unstubAllGlobals());

test("sends reply text only and plays all received audio frames in order", async () => {
  renderReply();
  fireEvent.click(read());
  expect(stop()).toHaveAttribute("aria-pressed", "true");
  const [socket] = sockets;
  expect(socket.url).toMatch(/\/api\/voice\/tts\/ws$/);
  expect(socket.binaryType).toBe("arraybuffer");
  socket.onopen?.();
  expect(socket.send).toHaveBeenCalledWith(
    JSON.stringify({ text: "第一句。\n\n第二句。" })
  );

  await act(async () => {
    socket.onmessage?.({ data: new Uint8Array([1, 2]).buffer });
    socket.onmessage?.({ data: new Uint8Array([1, 2]).buffer });
    socket.onmessage?.({ data: '{"status":"completed"}' });
  });
  const audio = player.decodeAudioData.mock.calls[0][0] as ArrayBuffer;
  expect(Array.from(new Uint8Array(audio))).toEqual([1, 2, 1, 2]);
  expect(player.start).toHaveBeenCalledOnce();
  expect(socket.close).toHaveBeenCalledOnce();
  act(() => player.end?.());
  expect(read()).toBeEnabled();
  expect(player.close).toHaveBeenCalledOnce();
});

test("stops pending synthesis and releases resources when leaving the conversation", () => {
  const view = renderReply();
  fireEvent.click(read());
  fireEvent.click(stop());
  expect(sockets[0].close).toHaveBeenCalledOnce();
  expect(player.start).not.toHaveBeenCalled();
  fireEvent.click(read());
  view.unmount();
  expect(sockets[1].close).toHaveBeenCalledOnce();
  expect(player.close).toHaveBeenCalledTimes(2);
});

test("reports failed synthesis and allows retry", async () => {
  renderReply();
  fireEvent.click(read());
  sockets[0].onmessage?.({ data: '{"status":"completed"}' });
  await waitFor(() =>
    expect(state.reportError).toHaveBeenCalledWith(
      "chat.thread.readAloudFailed"
    )
  );
  expect(read()).toBeEnabled();
  expect(player.start).not.toHaveBeenCalled();
  expect(sockets[0].close).toHaveBeenCalledOnce();
});

test("omits read-aloud when the tenant has no default speech model", () => {
  state.modelName = "";
  renderReply();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

test("hides read-aloud and cancels speech when the default model is cleared", () => {
  const view = renderReply();
  fireEvent.click(read());

  state.modelName = "";
  view.rerender(reply());
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(sockets[0].close).toHaveBeenCalledOnce();
  expect(player.close).toHaveBeenCalledOnce();

  state.modelName = "qwen3-tts-flash-realtime";
  view.rerender(reply());
  expect(read()).toBeEnabled();
});
