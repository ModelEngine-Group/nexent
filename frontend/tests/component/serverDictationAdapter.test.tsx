// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, expect, test, vi } from "vitest";
import { ServerDictationAdapter } from "@/app/newchat/adapter/server-dictation-adapter";
import { conversationService } from "@/services/conversationService";

test.each(["speech_istreaming", "volc.seedasr.sauc.duration"])(
  "sends the selected Volcano STT model %s when chat connects",
  async (modelName) => {
    const socket = {
      readyState: WebSocket.OPEN,
      onopen: null as (() => void) | null,
      send: vi.fn(),
      close: vi.fn(),
    };
    vi.spyOn(conversationService.stt, "createWebSocket").mockReturnValue(
      socket as unknown as WebSocket
    );
    vi.stubGlobal("navigator", {
      mediaDevices: { getUserMedia: async () => ({ getTracks: () => [] }) },
    });
    const node = { connect: vi.fn(), disconnect: vi.fn() };
    vi.stubGlobal(
      "AudioContext",
      class {
        state = "running";
        createMediaStreamSource = () => node;
        createScriptProcessor = () => node;
        createGain = () => ({ ...node, gain: { value: 1 } });
        close = async () => undefined;
      }
    );
    const session = new ServerDictationAdapter(() => ({
      modelName,
      displayName: modelName,
      modelFactory: "volcengine",
      modelAppid: "test-app",
      accessToken: "test-token",
      apiConfig: { apiKey: "", modelUrl: "wss://example.test/stt" },
    })).listen();

    try {
      await vi.waitFor(() => expect(socket.onopen).toBeTypeOf("function"));
      socket.onopen?.();
      expect(JSON.parse(socket.send.mock.calls[0][0])).toMatchObject({
        model: modelName,
        model_factory: "volcengine",
        model_appid: "test-app",
        access_token: "test-token",
        base_url: "wss://example.test/stt",
      });
      vi.useFakeTimers();
      const stopped = session.stop();
      if (modelName === "volc.seedasr.sauc.duration") {
        expect(socket.send.mock.calls[1][0]).toEqual(new ArrayBuffer(0));
      } else {
        expect(socket.send).toHaveBeenCalledTimes(1);
      }
      await vi.advanceTimersByTimeAsync(1500);
      await stopped;
    } finally {
      session.cancel();
    }
  }
);

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
