import type { DictationAdapter } from "@assistant-ui/react";

import type { STTModelConfig } from "@/types/modelConfig";
import { conversationService } from "@/services/conversationService";

export type DictationConfigProvider = () => STTModelConfig | undefined;

const STOP_FLUSH_TIMEOUT_MS = 1500;

const getTextFromResponse = (response: Record<string, unknown>): string => {
  if (typeof response.text === "string") return response.text;

  const result = response.result;
  if (result && typeof result === "object" && "text" in result) {
    const text = (result as { text?: unknown }).text;
    if (typeof text === "string") return text;
  }

  return "";
};

export class ServerDictationAdapter implements DictationAdapter {
  disableInputDuringDictation = false;

  constructor(private readonly getConfig: DictationConfigProvider) {}

  listen(): DictationAdapter.Session {
    const speechStartCallbacks = new Set<() => void>();
    const speechEndCallbacks = new Set<
      (result: DictationAdapter.Result) => void
    >();
    const speechCallbacks = new Set<
      (result: DictationAdapter.Result) => void
    >();
    const config = this.getConfig();

    let stream: MediaStream | undefined;
    let audioContext: AudioContext | undefined;
    let processor: ScriptProcessorNode | undefined;
    let socket: WebSocket | undefined;
    let stopTimer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    let cancelled = false;
    let hasSpeech = false;

    const session: DictationAdapter.Session = {
      status: { type: "starting" },
      stop: async () => {
        if (stopped || cancelled) return;
        stopped = true;
        this.stopAudioCapture(stream, audioContext, processor);

        await new Promise<void>((resolve) => {
          stopTimer = setTimeout(() => {
            this.closeSocket(socket);
            resolve();
          }, STOP_FLUSH_TIMEOUT_MS);

          if (!socket || socket.readyState === WebSocket.CLOSED) {
            clearTimeout(stopTimer);
            stopTimer = undefined;
            resolve();
          }
        });

        if (session.status.type !== "ended") {
          session.status = { type: "ended", reason: "stopped" };
        }
      },
      cancel: () => {
        if (cancelled) return;
        cancelled = true;
        stopped = true;
        if (stopTimer) clearTimeout(stopTimer);
        this.stopAudioCapture(stream, audioContext, processor);
        this.closeSocket(socket);
        session.status = { type: "ended", reason: "cancelled" };
      },
      onSpeechStart: (callback) => {
        speechStartCallbacks.add(callback);
        return () => speechStartCallbacks.delete(callback);
      },
      onSpeechEnd: (callback) => {
        speechEndCallbacks.add(callback);
        return () => speechEndCallbacks.delete(callback);
      },
      onSpeech: (callback) => {
        speechCallbacks.add(callback);
        return () => speechCallbacks.delete(callback);
      },
    };

    const emitSpeech = (result: DictationAdapter.Result) => {
      if (!result.transcript || cancelled) return;
      speechCallbacks.forEach((callback) => callback(result));
      if (result.isFinal) {
        speechEndCallbacks.forEach((callback) => callback(result));
      }
    };

    const fail = () => {
      if (cancelled) return;
      this.stopAudioCapture(stream, audioContext, processor);
      this.closeSocket(socket);
      session.status = { type: "ended", reason: "error" };
    };

    void this.startSession({
      config,
      session,
      emitSpeech,
      fail,
      setResources: (resources) => {
        stream = resources.stream;
        audioContext = resources.audioContext;
        processor = resources.processor;
        socket = resources.socket;
      },
      onSpeechStarted: () => {
        if (!hasSpeech && !cancelled) {
          hasSpeech = true;
          speechStartCallbacks.forEach((callback) => callback());
        }
      },
    });

    return session;
  }

  private async startSession(args: {
    config: STTModelConfig | undefined;
    session: DictationAdapter.Session;
    emitSpeech: (result: DictationAdapter.Result) => void;
    fail: () => void;
    setResources: (resources: {
      stream: MediaStream;
      audioContext: AudioContext;
      processor: ScriptProcessorNode;
      socket: WebSocket;
    }) => void;
    onSpeechStarted: () => void;
  }): Promise<void> {
    try {
      const stream = await navigator.mediaDevices.getUserMedia(
        conversationService.stt.getAudioConstraints()
      );
      if (args.session.status.type === "ended") {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      const audioContext = new AudioContext(
        conversationService.stt.getAudioContextOptions()
      );
      if (audioContext.state === "suspended") await audioContext.resume();

      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      const silentOutput = audioContext.createGain();
      silentOutput.gain.value = 0;
      source.connect(processor);
      processor.connect(silentOutput);
      silentOutput.connect(audioContext.destination);

      const socket = conversationService.stt.createWebSocket();
      args.setResources({ stream, audioContext, processor, socket });

      socket.onopen = () => {
        if (args.session.status.type === "ended") {
          this.stopAudioCapture(stream, audioContext, processor);
          this.closeSocket(socket);
          return;
        }
        socket.send(JSON.stringify(this.buildConfig(args.config)));
        args.session.status = { type: "running" };
        args.onSpeechStarted();
      };

      socket.onmessage = (event) => {
        try {
          const response = JSON.parse(event.data) as Record<string, unknown>;
          if (response.error) {
            args.fail();
            return;
          }

          if (response.vad === "started") args.onSpeechStarted();
          const transcript = getTextFromResponse(response);
          if (transcript) {
            args.emitSpeech({
              transcript,
              isFinal: response.is_final === true,
            });
          }
        } catch {
          args.fail();
        }
      };

      socket.onerror = args.fail;
      socket.onclose = () => {
        if (args.session.status.type !== "ended") {
          args.session.status = {
            type: "ended",
            reason: "stopped",
          };
        }
      };

      processor.onaudioprocess = (event) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const pcmData = conversationService.stt.processAudioData(
          event.inputBuffer.getChannelData(0)
        );
        if (pcmData.length > 0) socket.send(pcmData.buffer);
      };
    } catch {
      args.fail();
    }
  }

  private buildConfig(
    config: STTModelConfig | undefined
  ): Record<string, string> {
    const isVolcSTT = config?.modelFactory === "volcengine";
    if (isVolcSTT) {
      return {
        language: "zh",
        model_factory: "volcengine",
        model_appid: config?.modelAppid || "",
        access_token: config?.accessToken || "",
        base_url:
          config?.apiConfig?.modelUrl ||
          "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
      };
    }

    return {
      language: "zh",
      api_key: config?.apiConfig?.apiKey || "sk-no-api-key",
      model: config?.modelName || "qwen3-asr-flash-realtime",
      base_url: config?.apiConfig?.modelUrl || "",
    };
  }

  private stopAudioCapture(
    stream: MediaStream | undefined,
    audioContext: AudioContext | undefined,
    processor: ScriptProcessorNode | undefined
  ): void {
    if (processor) processor.onaudioprocess = null;
    stream?.getTracks().forEach((track) => track.stop());
    void audioContext?.close();
  }

  private closeSocket(socket: WebSocket | undefined): void {
    if (socket && socket.readyState !== WebSocket.CLOSED) socket.close();
  }
}
