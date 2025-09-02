import asyncio
import logging

from fastapi import APIRouter, WebSocket
from nexent.core.models.stt_model import STTConfig, STTModel
from nexent.core.models.tts_model import TTSConfig, TTSModel

from consts.const import APPID, CLUSTER, SPEED_RATIO, TEST_VOICE_PATH, TOKEN, VOICE_TYPE

logger = logging.getLogger("voice_app")


class VoiceService:
    """Unified voice service that hosts both STT and TTS on a single FastAPI application"""

    def __init__(self):
        """
        Initialize the voice service with configurations from const.py.
        """
        # Initialize STT configuration
        self.stt_config = STTConfig(
            appid=APPID,
            token=TOKEN
        )

        # Initialize TTS configuration
        self.tts_config = TTSConfig(
            appid=APPID,
            token=TOKEN,
            cluster=CLUSTER,
            voice_type=VOICE_TYPE,
            speed_ratio=SPEED_RATIO
        )

        # Initialize models
        self.stt_model = STTModel(self.stt_config, TEST_VOICE_PATH)
        self.tts_model = TTSModel(self.tts_config)

        # Create FastAPI application
        self.router = APIRouter(prefix="/voice")

        # Set up routes
        self._setup_routes()

    def _setup_routes(self):
        """Configure API routes for voice services"""

        # STT WebSocket route
        @self.router.websocket("/stt/ws")
        async def stt_websocket(websocket: WebSocket):
            """WebSocket endpoint for real-time audio streaming and STT"""
            logger.info("STT WebSocket connection attempt...")
            await websocket.accept()
            logger.info("STT WebSocket connection accepted")
            try:
                # Start streaming session
                await self.stt_model.start_streaming_session(websocket)
            except Exception as e:
                logger.error(f"STT WebSocket error: {str(e)}")
                import traceback
                traceback.print_exc()
                await websocket.send_json({"error": str(e)})
            finally:
                logger.info("STT WebSocket connection closed")

        # TTS WebSocket route
        @self.router.websocket("/tts/ws")
        async def tts_websocket(websocket: WebSocket):
            """WebSocket endpoint for streaming TTS"""
            logger.info("TTS WebSocket connection attempt...")
            await websocket.accept()
            logger.info("TTS WebSocket connection accepted")

            try:
                # Receive text from client (single request)
                data = await websocket.receive_json()
                text = data.get("text")

                if not text:
                    if websocket.client_state.name == "CONNECTED":
                        await websocket.send_json({"error": "No text provided"})
                    return

                # Generate and stream audio chunks
                try:
                    # First try to use it as a coroutine that returns an async iterator
                    speech_result = await self.tts_model.generate_speech(text, stream=True)

                    # Check if it's an async iterator or a regular iterable
                    if hasattr(speech_result, '__aiter__'):
                        # It's an async iterator, use async for
                        async for chunk in speech_result:
                            if websocket.client_state.name == "CONNECTED":
                                await websocket.send_bytes(chunk)
                            else:
                                break
                    elif hasattr(speech_result, '__iter__'):
                        # It's a regular iterator, use normal for
                        for chunk in speech_result:
                            if websocket.client_state.name == "CONNECTED":
                                await websocket.send_bytes(chunk)
                            else:
                                break
                    else:
                        # It's a single chunk, send it directly
                        if websocket.client_state.name == "CONNECTED":
                            await websocket.send_bytes(speech_result)

                    await asyncio.sleep(0.1)

                except TypeError as te:
                    # If speech_result is still a coroutine, try calling it directly without stream=True
                    if "async for" in str(te) and "requires an object with __aiter__" in str(te):
                        logger.error("Falling back to non-streaming TTS")
                        speech_data = await self.tts_model.generate_speech(text, stream=False)
                        if websocket.client_state.name == "CONNECTED":
                            await websocket.send_bytes(speech_data)
                    else:
                        raise

                # Send end marker after successful TTS generation
                if websocket.client_state.name == "CONNECTED":
                    await websocket.send_json({"status": "completed"})

            except Exception as e:
                logger.error(f"TTS WebSocket error: {str(e)}")
                import traceback
                traceback.print_exc()
                await websocket.send_json({"error": str(e)})
            finally:
                logger.info("TTS WebSocket connection closed")
                # Ensure connection is properly closed
                if websocket.client_state.name == "CONNECTED":
                    await websocket.close()

    async def check_connectivity(self, model_type: str) -> bool:
        """
        Check the connectivity status of voice services (STT and TTS)

        Args:
            model_type: The type of model to check, options are 'stt', 'tts'

        Returns:
            bool: Returns True if all services are connected normally, False if any service connection fails
        """
        try:
            stt_connected = False
            tts_connected = False

            if model_type == 'stt':
                logging.info(f'STT Config: {self.stt_config}')
                stt_connected = await self.stt_model.check_connectivity()
                if not stt_connected:
                    logging.error(
                        "Speech Recognition (STT) service connection failed")

            if model_type == 'tts':
                logging.info(f'TTS Config: {self.tts_config}')
                tts_connected = await self.tts_model.check_connectivity()
                if not tts_connected:
                    logging.error(
                        "Text-to-Speech (TTS) service connection failed")

            # Return the corresponding connection status based on model_type
            if model_type == 'stt':
                return stt_connected
            elif model_type == 'tts':
                return tts_connected
            else:
                logging.error(f"Unknown model type: {model_type}")
                return False

        except Exception as e:
            logging.error(
                f"Voice service connectivity test encountered an exception: {str(e)}")
            return False


router = VoiceService().router
