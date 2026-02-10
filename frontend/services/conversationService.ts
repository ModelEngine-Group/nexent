import { API_ENDPOINTS, ApiError } from './api';

import { chatConfig } from '@/const/chatConfig';
import type { 
  ConversationListResponse, 
  ConversationListItem,
  ApiConversationResponse
} from '@/types/conversation';
import { getAuthHeaders, fetchWithAuth } from '@/lib/auth';
import log from "@/lib/logger";

// @ts-ignore
const fetch = fetchWithAuth;

// This helper function now ALWAYS connects through the current host and port.
// This relies on our custom `server.js` to handle the proxying in all environments.
const getWebSocketUrl = (endpoint: string): string => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}${endpoint}`;
  log.log(`[WebSocket] Connecting via server proxy: ${wsUrl}`);
  return wsUrl;
};

export const conversationService = {
  // Get conversation list
  async getList(): Promise<ConversationListItem[]> {
    const response = await fetch(API_ENDPOINTS.conversation.list);

    const data = await response.json() as ConversationListResponse;
    
    if (data.code === 0) {
      return data.data || [];
    }
    
    throw new ApiError(data.code, data.message);
  },

  // Create new conversation
  async create(title?: string) {
    const response = await fetch(API_ENDPOINTS.conversation.create, {
      method: 'PUT',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        title: title || "new conversation"
      }),
    });

    const data = await response.json();
    
    if (data.code === 0) {
      return data.data;
    }
    
    throw new ApiError(data.code, data.message);
  },

  // Rename conversation
  async rename(conversationId: number, name: string) {
    const response = await fetch(API_ENDPOINTS.conversation.rename, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        conversation_id: conversationId,
        name,
      }),
    });

    const data = await response.json();
    
    if (data.code === 0) {
      return data.data;
    }
    
    throw new ApiError(data.code, data.message);
  },

  // Get conversation details
  async getDetail(conversationId: number, signal?: AbortSignal): Promise<ApiConversationResponse> {
    try {
      const response = await fetch(API_ENDPOINTS.conversation.detail(conversationId), {
        method: 'GET',
        headers: getAuthHeaders(),
        signal,
      });

      // If the signal is aborted before the request returns, return early
      if (signal?.aborted) {
        return { code: -1, message: "请求已取消", data: [] };
      }

      const data = await response.json();
      
      if (data.code === 0) {
        return data;
      }
      
      throw new ApiError(data.code, data.message);
    } catch (error: any) {
      // If the error is caused by canceling the request, return a specific response instead of throwing an error
      if (error instanceof Error && error.name === 'AbortError' || signal?.aborted) {
        return { code: -1, message: "请求已取消", data: [] };
      }
      throw error;
    }
  },

  // Delete conversation
  async delete(conversationId: number) {
    const response = await fetch(API_ENDPOINTS.conversation.delete(conversationId), {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });

    const data = await response.json();
    
    if (data.code === 0) {
      return true;
    }
    
    throw new ApiError(data.code, data.message);
  },

  // Stop conversation agent
  async stop(conversationId: number) {
    const response = await fetch(API_ENDPOINTS.agent.stop(conversationId), {
      method: 'GET',
      headers: getAuthHeaders(),
    });

    const data = await response.json();
    
    if (data.status === 'success') {
      return true;
    }
    
    throw new ApiError(data.code || -1, data.message || data.detail || '停止失败');
  },

  // STT related functionality
  stt: {
    // Create WebSocket connection
    createWebSocket(): WebSocket {
      return new WebSocket(getWebSocketUrl(API_ENDPOINTS.stt.ws));
    },

    // Process audio data
    processAudioData(inputData: Float32Array): Int16Array {
      const pcmData = new Int16Array(inputData.length);
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]));
        pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      return pcmData;
    },

    // Get audio configuration
    getAudioConstraints() {
      return {
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      };
    },

    // Get audio context configuration
    getAudioContextOptions() {
      return {
        sampleRate: 16000,
      };
    }
  },

  // Add TTS related functionality
  tts: {
    // Create WebSocket connection
    // TODO: explain why we need to create a WebSocket connection for TTS
    createWebSocket(): WebSocket {
      return new WebSocket(getWebSocketUrl(API_ENDPOINTS.tts.ws));
    },

    // TTS playback status management
    createTTSService() {
      const audioRef = { current: null as HTMLAudioElement | null };
      const wsRef = { current: null as WebSocket | null };
      const audioChunksRef = { current: [] as Uint8Array[] };
      const mediaSourceRef = { current: null as MediaSource | null };
      const sourceBufferRef = { current: null as SourceBuffer | null };
      const isStreamingPlaybackRef = { current: false };
      const pendingChunksRef = { current: [] as Uint8Array[] };

      // Play audio (main entry)
      const playAudio = async (text: string, onStatusChange?: (status: typeof chatConfig.ttsStatus[keyof typeof chatConfig.ttsStatus]) => void): Promise<void> => {
        if (!text) return;

        try {
          onStatusChange?.(chatConfig.ttsStatus.GENERATING);
          audioChunksRef.current = [];
          pendingChunksRef.current = [];

          if (!window.MediaSource) {
            await playAudioTraditional(text, onStatusChange);
            return;
          }

          await initStreamingPlayback(onStatusChange);
          
          const wsUrl = getWebSocketUrl(API_ENDPOINTS.tts.ws);
          const ws = new WebSocket(wsUrl);
          wsRef.current = ws;

          ws.onopen = () => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ text }));
            }
          };

          ws.onmessage = async (event) => {
            try {
              if (event.data instanceof Blob) {
                const arrayBuffer = await event.data.arrayBuffer();
                const uint8Array = new Uint8Array(arrayBuffer);
                if (uint8Array.length > 0) {
                  if (isStreamingPlaybackRef.current) {
                    await handleStreamingAudioChunk(uint8Array, onStatusChange);
                  } else {
                    audioChunksRef.current.push(uint8Array);
                  }
                }
              } else if (event.data instanceof ArrayBuffer) {
                const uint8Array = new Uint8Array(event.data);
                if (uint8Array.length > 0) {
                  if (isStreamingPlaybackRef.current) {
                    await handleStreamingAudioChunk(uint8Array, onStatusChange);
                  } else {
                    audioChunksRef.current.push(uint8Array);
                  }
                }
              } else if (typeof event.data === 'string') {
                try {
                  const data = JSON.parse(event.data);
                  if (data.status === 'completed') {
                    if (isStreamingPlaybackRef.current) {
                      await finalizeStreamingPlayback();
                    } else {
                      if (audioChunksRef.current.length > 0) {
                        playAudioChunks(onStatusChange);
                      } else {
                        onStatusChange?.(chatConfig.ttsStatus.ERROR);
                        setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
                      }
                    }
                    
                    setTimeout(() => {
                      if (wsRef.current) {
                        wsRef.current.close();
                        wsRef.current = null;
                      }
                    }, 100);
                  } else if (data.error) {
                    onStatusChange?.(chatConfig.ttsStatus.ERROR);
                    setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
                    cleanupStreamingPlayback();
                    if (wsRef.current) {
                      wsRef.current.close();
                      wsRef.current = null;
                    }
                  }
                } catch (e) {
                  // JSON parse error
                }
              }
            } catch (error) {
              // Message handling error
            }
          };

          ws.onerror = () => {
            onStatusChange?.(chatConfig.ttsStatus.ERROR);
            setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
            cleanupStreamingPlayback();
          };

          ws.onclose = (event) => {
            wsRef.current = null;
            if (event.code !== 1000) {
              onStatusChange?.(chatConfig.ttsStatus.ERROR);
              setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
              cleanupStreamingPlayback();
            }
          };

        } catch (error) {
          onStatusChange?.(chatConfig.ttsStatus.ERROR);
          setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
          cleanupStreamingPlayback();
        }
      };

      // Initialize streaming playback
      const initStreamingPlayback = async (onStatusChange?: (status: typeof chatConfig.ttsStatus[keyof typeof chatConfig.ttsStatus]) => void): Promise<void> => {
        return new Promise((resolve, reject) => {
          try {
            const mediaSource = new MediaSource();
            mediaSourceRef.current = mediaSource;
            
            if (audioRef.current) {
              audioRef.current.pause();
              audioRef.current = null;
            }
            
            const audio = new Audio();
            audio.src = URL.createObjectURL(mediaSource);
            audioRef.current = audio;
            
            audio.oncanplay = () => {
              onStatusChange?.('playing');
            };
            
            audio.onended = () => {
              onStatusChange?.('idle');
              cleanupStreamingPlayback();
            };
            
            audio.onerror = () => {
              onStatusChange?.('error');
              setTimeout(() => onStatusChange?.('idle'), 2000);
              cleanupStreamingPlayback();
            };
            
            mediaSource.addEventListener('sourceopen', () => {
              try {
                const sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
                sourceBufferRef.current = sourceBuffer;
                
                sourceBuffer.addEventListener('updateend', () => {
                  processPendingChunks();
                });
                
                sourceBuffer.addEventListener('error', () => {
                  onStatusChange?.('error');
                  setTimeout(() => onStatusChange?.('idle'), 2000);
                });
                
                isStreamingPlaybackRef.current = true;
                resolve();
                
              } catch (error) {
                reject(error);
              }
            });
            
            mediaSource.addEventListener('sourceclose', () => {
              isStreamingPlaybackRef.current = false;
            });
            
            mediaSource.addEventListener('error', (e) => {
              reject(e);
            });
            
          } catch (error) {
            reject(error);
          }
        });
      };

      // Process streaming audio chunks
      const handleStreamingAudioChunk = async (chunk: Uint8Array, onStatusChange?: (status: typeof chatConfig.ttsStatus[keyof typeof chatConfig.ttsStatus]) => void) => {
        if (!isStreamingPlaybackRef.current || !sourceBufferRef.current) {
          pendingChunksRef.current.push(chunk);
          return;
        }
        
        try {
          if (sourceBufferRef.current.updating) {
            pendingChunksRef.current.push(chunk);
          } else {
            sourceBufferRef.current.appendBuffer(chunk.buffer.slice(0) as ArrayBuffer);
            
            if (audioRef.current && audioRef.current.paused && audioRef.current.readyState >= 2) {
              try {
                await audioRef.current.play();
                onStatusChange?.('playing');
              } catch (playError) {
                // Auto-play failed
              }
            }
          }
        } catch (error) {
          cleanupStreamingPlayback();
          audioChunksRef.current.push(chunk);
          audioChunksRef.current.push(...pendingChunksRef.current);
          pendingChunksRef.current = [];
          isStreamingPlaybackRef.current = false;
        }
      };

      // Process pending audio chunks
      const processPendingChunks = () => {
        if (!sourceBufferRef.current || sourceBufferRef.current.updating || pendingChunksRef.current.length === 0) {
          return;
        }
        
        try {
          const chunk = pendingChunksRef.current.shift();
          if (chunk) {
            sourceBufferRef.current.appendBuffer(chunk.buffer.slice(0) as ArrayBuffer);
          }
        } catch (error) {
          // Processing error
        }
      };

      // Complete streaming playback
      const finalizeStreamingPlayback = async () => {
        if (pendingChunksRef.current.length > 0 && sourceBufferRef.current) {
          const waitForPending = () => {
            return new Promise<void>((resolve) => {
              const checkPending = () => {
                if (pendingChunksRef.current.length === 0 || !sourceBufferRef.current?.updating) {
                  resolve();
                } else {
                  setTimeout(checkPending, 100);
                }
              };
              checkPending();
            });
          };
          
          await waitForPending();
        }
        
        if (mediaSourceRef.current && mediaSourceRef.current.readyState === 'open') {
          try {
            mediaSourceRef.current.endOfStream();
          } catch (error) {
            // End stream error
          }
        }
      };

      // Clean up streaming playback resources
      const cleanupStreamingPlayback = () => {
        isStreamingPlaybackRef.current = false;
        pendingChunksRef.current = [];
        
        if (sourceBufferRef.current) {
          sourceBufferRef.current = null;
        }
        
        if (mediaSourceRef.current) {
          try {
            if (mediaSourceRef.current.readyState === 'open') {
              mediaSourceRef.current.endOfStream();
            }
          } catch (error) {
            // Already closed
          }
          mediaSourceRef.current = null;
        }
        
        if (audioRef.current && audioRef.current.src.startsWith('blob:')) {
          URL.revokeObjectURL(audioRef.current.src);
        }
      };

      // Traditional playback method
      const playAudioTraditional = async (text: string, onStatusChange?: (status: typeof chatConfig.ttsStatus[keyof typeof chatConfig.ttsStatus]) => void) => {
        audioChunksRef.current = [];
        const wsUrl = getWebSocketUrl(API_ENDPOINTS.tts.ws);
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ text }));
          }
        };

        ws.onmessage = async (event) => {
          try {
            if (event.data instanceof Blob) {
              const arrayBuffer = await event.data.arrayBuffer();
              const uint8Array = new Uint8Array(arrayBuffer);
              if (uint8Array.length > 0) {
                audioChunksRef.current.push(uint8Array);
              }
            } else if (event.data instanceof ArrayBuffer) {
              const uint8Array = new Uint8Array(event.data);
              if (uint8Array.length > 0) {
                audioChunksRef.current.push(uint8Array);
              }
            } else if (typeof event.data === 'string') {
              try {
                const data = JSON.parse(event.data);
                if (data.status === 'completed') {
                  setTimeout(() => {
                    if (wsRef.current) {
                      wsRef.current.close();
                      wsRef.current = null;
                    }
                  }, 100);
                  
                  if (audioChunksRef.current.length > 0) {
                    playAudioChunks(onStatusChange);
                  } else {
                    onStatusChange?.(chatConfig.ttsStatus.ERROR);
                    setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
                  }
                } else if (data.error) {
                  onStatusChange?.(chatConfig.ttsStatus.ERROR);
                  setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
                  if (wsRef.current) {
                    wsRef.current.close();
                    wsRef.current = null;
                  }
                }
              } catch (e) {
                // Parse error
              }
            }
          } catch (error) {
            // Message error
          }
        };

        ws.onerror = () => {
          onStatusChange?.(chatConfig.ttsStatus.ERROR);
          setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
        };

        ws.onclose = () => {
          wsRef.current = null;
        };
      };

      // Play audio chunks (traditional mode)
      const playAudioChunks = (onStatusChange?: (status: typeof chatConfig.ttsStatus[keyof typeof chatConfig.ttsStatus]) => void) => {
        if (audioChunksRef.current.length === 0) {
          onStatusChange?.('idle');
          return;
        }

        try {
          const validChunks = audioChunksRef.current.filter(chunk => chunk && chunk.length > 0);
          
          if (validChunks.length === 0) {
            onStatusChange?.(chatConfig.ttsStatus.ERROR);
            setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
            return;
          }

          const chunkHashes = new Set();
          const uniqueChunks = [];
          
          for (let i = 0; i < validChunks.length; i++) {
            const chunk = validChunks[i];
            const hashData = chunk.length > 32 ? 
              Array.from(chunk.slice(0, 16)).concat(Array.from(chunk.slice(-16))) :
              Array.from(chunk);
            const hash = hashData.join(',');
            
            if (!chunkHashes.has(hash)) {
              chunkHashes.add(hash);
              uniqueChunks.push(chunk);
            }
          }

          const totalLength = uniqueChunks.reduce((sum, chunk) => sum + chunk.length, 0);
          const combinedArray = new Uint8Array(totalLength);
          let offset = 0;
          
          for (let i = 0; i < uniqueChunks.length; i++) {
            const chunk = uniqueChunks[i];
            
            if (offset + chunk.length > totalLength) {
              continue;
            }
            
            combinedArray.set(chunk, offset);
            offset += chunk.length;
          }

          const finalArray = offset === totalLength ? combinedArray : combinedArray.slice(0, offset);
          
          if (finalArray.length < 100) {
            onStatusChange?.(chatConfig.ttsStatus.ERROR);
            setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
            return;
          }
          
          const hasValidMP3Header = finalArray.length >= 3 && (
            (finalArray[0] === 0xFF && (finalArray[1] & 0xE0) === 0xE0) ||
            (finalArray[0] === 0x49 && finalArray[1] === 0x44 && finalArray[2] === 0x33)
          );
          
          if (!hasValidMP3Header) {
            onStatusChange?.(chatConfig.ttsStatus.ERROR);
            setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
            return;
          }

          const audioBlob = new Blob([finalArray], { type: 'audio/mpeg' });
          const audioUrl = URL.createObjectURL(audioBlob);
          
          if (audioRef.current) {
            audioRef.current.pause();
            audioRef.current = null;
          }

          const audio = new Audio(audioUrl);
          audioRef.current = audio;

          audio.oncanplay = () => {
            onStatusChange?.('playing');
          };

          audio.onended = () => {
            onStatusChange?.(chatConfig.ttsStatus.IDLE);
            URL.revokeObjectURL(audioUrl);
            audioRef.current = null;
            audioChunksRef.current = [];
          };

          audio.onerror = () => {
            onStatusChange?.(chatConfig.ttsStatus.ERROR);
            setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
            URL.revokeObjectURL(audioUrl);
            audioRef.current = null;
            audioChunksRef.current = [];
          };

          audio.play().then(() => {
            onStatusChange?.('playing');
          }).catch(() => {
            onStatusChange?.(chatConfig.ttsStatus.ERROR);
            setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
            URL.revokeObjectURL(audioUrl);
            audioChunksRef.current = [];
          });

        } catch (error) {
          onStatusChange?.(chatConfig.ttsStatus.ERROR);
          setTimeout(() => onStatusChange?.(chatConfig.ttsStatus.IDLE), 2000);
          audioChunksRef.current = [];
        }
      };

      // stop audio
      const stopAudio = () => {
        if (wsRef.current) {
          wsRef.current.close();
          wsRef.current = null;
        }

        if (audioRef.current) {
          audioRef.current.pause();
          audioRef.current = null;
        }

        cleanupStreamingPlayback();
        audioChunksRef.current = [];
      };

      // clean up resources
      const cleanup = () => {
        stopAudio();
        cleanupStreamingPlayback();
      };

      return {
        playAudio,
        stopAudio,
        cleanup
      };
    }
  },

  // Add file preprocess method
  async preprocessFiles(query: string, files: File[], conversationId?: number, signal?: AbortSignal): Promise<ReadableStreamDefaultReader<Uint8Array>> {
    try {
      // Use FormData to handle file upload
      const formData = new FormData();
      formData.append('query', query);

      // Add files
      if (files && files.length > 0) {
        files.forEach(file => {
          formData.append('files', file);
        });
      }

      // Build URL with conversation_id as query parameter
      let url = API_ENDPOINTS.storage.preprocess;
      if (conversationId !== undefined && conversationId !== null) {
        url += `?conversation_id=${conversationId}`;
      }

      const response = await fetch(url, {
        method: 'POST',
        body: formData,
        signal,
      });

      // Check if the response is successful
      if (!response.ok) {
        // Handle specific HTTP status codes with error codes for internationalization
        if (response.status === 413) {
          throw new Error('REQUEST_ENTITY_TOO_LARGE');
        } else {
          throw new Error('FILE_PARSING_FAILED');
        
        }
      }

      if (!response.body) {
        throw new Error("Response body is null");
      }

      return response.body.getReader();
    } catch (error) {
      // If the error is caused by canceling the request, return a specific response instead of throwing an error
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error('Request has been aborted');
      }
      // Other errors are thrown normally
      throw error;
    }
  },

  // Add run agent method
  async runAgent(params: {
    query: string;
    conversation_id: number;
    is_set: boolean;
    history: Array<{ role: string; content: string; }>;
    files?: File[];  // Add optional files parameter
    minio_files?: Array<{
      object_name: string;
      name: string;
      type: string;
      size: number;
      url?: string;
      description?: string; // Add file description field
    }>; // Update to complete attachment information object array
    agent_id?: number; // Add agent_id parameter
    is_debug?: boolean; // Add debug mode parameter
  }, signal?: AbortSignal) {
    try {
      // Construct request parameters
      const requestParams: any = {
        query: params.query,
        conversation_id: params.conversation_id,
        is_set: params.is_set,
        history: params.history,
        minio_files: params.minio_files || null,
        is_debug: params.is_debug || false,
      };
      
      // Only include agent_id if it has a value
      if (params.agent_id !== undefined && params.agent_id !== null) {
        requestParams.agent_id = params.agent_id;
      }

      const response = await fetch(API_ENDPOINTS.agent.run, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(requestParams),
        signal,
      });

      if (!response.body) {
        throw new Error("Response body is null");
      }

      return response.body.getReader();
    } catch (error: any) {
      // If the error is caused by canceling the request, return a specific response instead of throwing an error
      if (error instanceof Error && error.name === 'AbortError') {
        log.log('Agent请求已被取消');
        throw new Error('请求已被取消');
      }
      // Other errors are thrown normally
      throw error;
    }
  },

  // Generate conversation title from user question
  async generateTitle(params: {
    conversation_id: number;
    question: string;
  }) {
    const response = await fetch(API_ENDPOINTS.conversation.generateTitle, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(params),
    });

    const data = await response.json();

    if (data.code === 0) {
      return data.data;
    }

    throw new ApiError(data.code, data.message);
  },

  // Like/dislike message
  async updateOpinion(params: { message_id: number; opinion: 'Y' | 'N' | null }) {
    const response = await fetch(API_ENDPOINTS.conversation.opinion, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(params),
    });
    const data = await response.json();
    if (data.code === 0) {
      return true;
    }
    throw new ApiError(data.code, data.message);
  },

  // Get message_id by conversationId and messageIndex
  async getMessageId(conversationId: number, messageIndex: number) {
    const response = await fetch(API_ENDPOINTS.conversation.messageId, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        conversation_id: conversationId,
        message_index: messageIndex
      })
    });

    const data = await response.json();
    
    if (data.code === 0) {
      return data.data;
    }
    
    throw new ApiError(data.code, data.message);
  },
}; 