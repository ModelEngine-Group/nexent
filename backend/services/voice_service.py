import asyncio
import logging
from typing import Dict, Any, Optional

from nexent.core.models.stt_model import STTConfig, STTModel
from nexent.core.models.tts_model import TTSConfig, TTSModel

from consts.const import APPID, CLUSTER, SPEED_RATIO, TEST_VOICE_PATH, TOKEN, VOICE_TYPE
from consts.exceptions import (
    VoiceServiceException,
    STTConnectionException,
    TTSConnectionException,
    VoiceConfigException
)

logger = logging.getLogger("voice_service")


class VoiceService:
    """Voice service that handles STT and TTS operations"""

    def __init__(self):
        """Initialize the voice service with configurations from const.py"""
        try:
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

        except Exception as e:
            logger.error(f"Failed to initialize voice service: {str(e)}")
            raise VoiceConfigException(f"Voice service initialization failed: {str(e)}") from e

    async def start_stt_streaming_session(self, websocket) -> None:
        """
        Start STT streaming session
        
        Args:
            websocket: WebSocket connection for real-time audio streaming
            
        Raises:
            STTConnectionException: If STT streaming fails
        """
        try:
            logger.info("Starting STT streaming session")
            await self.stt_model.start_streaming_session(websocket)
        except Exception as e:
            logger.error(f"STT streaming session failed: {str(e)}")
            raise STTConnectionException(f"STT streaming failed: {str(e)}") from e

    async def generate_tts_speech(self, text: str, stream: bool = True) -> Any:
        """
        Generate TTS speech from text
        
        Args:
            text: Text to convert to speech
            stream: Whether to stream the audio or return complete audio
            
        Returns:
            Audio data (streaming or complete)
            
        Raises:
            TTSConnectionException: If TTS generation fails
        """
        if not text:
            raise VoiceServiceException("No text provided for TTS generation")
            
        try:
            logger.info(f"Generating TTS speech for text: {text[:50]}...")
            speech_result = await self.tts_model.generate_speech(text, stream=stream)
            return speech_result
        except Exception as e:
            logger.error(f"TTS generation failed: {str(e)}")
            raise TTSConnectionException(f"TTS generation failed: {str(e)}") from e

    async def stream_tts_to_websocket(self, websocket, text: str) -> None:
        """
        Stream TTS audio to WebSocket with proper error handling and fallback
        
        Args:
            websocket: WebSocket connection to stream to
            text: Text to convert to speech
            
        Raises:
            TTSConnectionException: If TTS service connection fails
            VoiceServiceException: If TTS streaming fails
        """
        try:
            # Generate and stream audio chunks
            speech_result = await self.generate_tts_speech(text, stream=True)

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
                speech_data = await self.generate_tts_speech(text, stream=False)
                if websocket.client_state.name == "CONNECTED":
                    await websocket.send_bytes(speech_data)
            else:
                raise

        # Send end marker after successful TTS generation
        if websocket.client_state.name == "CONNECTED":
            await websocket.send_json({"status": "completed"})

    async def check_stt_connectivity(self) -> bool:
        """
        Check STT service connectivity
        
        Returns:
            bool: True if STT service is connected, False otherwise
            
        Raises:
            STTConnectionException: If connectivity check fails
        """
        try:
            logger.info(f"Checking STT connectivity with config: {self.stt_config}")
            connected = await self.stt_model.check_connectivity()
            if not connected:
                logger.error("STT service connection failed")
                raise STTConnectionException("STT service connection failed")
            return connected
        except STTConnectionException:
            raise
        except Exception as e:
            logger.error(f"STT connectivity check failed: {str(e)}")
            raise STTConnectionException(f"STT connectivity check failed: {str(e)}") from e

    async def check_tts_connectivity(self) -> bool:
        """
        Check TTS service connectivity
        
        Returns:
            bool: True if TTS service is connected, False otherwise
            
        Raises:
            TTSConnectionException: If connectivity check fails
        """
        try:
            logger.info(f"Checking TTS connectivity with config: {self.tts_config}")
            connected = await self.tts_model.check_connectivity()
            if not connected:
                logger.error("TTS service connection failed")
                raise TTSConnectionException("TTS service connection failed")
            return connected
        except TTSConnectionException:
            raise
        except Exception as e:
            logger.error(f"TTS connectivity check failed: {str(e)}")
            raise TTSConnectionException(f"TTS connectivity check failed: {str(e)}") from e

    async def check_voice_connectivity(self, model_type: str) -> bool:
        """
        Check voice service connectivity based on model type
        
        Args:
            model_type: Type of model to check ('stt' or 'tts')
            
        Returns:
            bool: True if the specified service is connected, False otherwise
            
        Raises:
            VoiceServiceException: If model_type is invalid
            STTConnectionException: If STT connectivity check fails
            TTSConnectionException: If TTS connectivity check fails
        """
        try:
            if model_type == 'stt':
                return await self.check_stt_connectivity()
            elif model_type == 'tts':
                return await self.check_tts_connectivity()
            else:
                logger.error(f"Unknown model type: {model_type}")
                raise VoiceServiceException(f"Unknown model type: {model_type}")
        except (STTConnectionException, TTSConnectionException):
            raise
        except Exception as e:
            logger.error(f"Voice service connectivity check failed: {str(e)}")
            raise VoiceServiceException(f"Voice service connectivity check failed: {str(e)}") from e


# Global voice service instance
_voice_service_instance: Optional[VoiceService] = None


def get_voice_service() -> VoiceService:
    """
    Get the global voice service instance
    
    Returns:
        VoiceService: The global voice service instance
    """
    global _voice_service_instance
    if _voice_service_instance is None:
        _voice_service_instance = VoiceService()
    return _voice_service_instance
