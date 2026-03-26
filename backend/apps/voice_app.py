import asyncio
import logging
from typing import Any, Dict, Optional

from nexent.core.models.volc_stt_model import VolcSTTConfig, VolcSTTModel
from nexent.core.models.ali_stt_model import AliSTTConfig, AliSTTModel
from nexent.core.models.stt_model import BaseSTTModel

from consts.const import APPID, CLUSTER, SPEED_RATIO, TEST_VOICE_PATH, TEST_PCM_PATH, TOKEN, VOICE_TYPE
from consts.exceptions import (
    VoiceServiceException,
    STTConnectionException,
    TTSConnectionException,
    VoiceConfigException
)
from database.model_management_db import get_model_records
from utils.config_utils import tenant_config_manager

logger = logging.getLogger("voice_service")


class VoiceService:
    """Voice service that handles STT and TTS operations"""

    def __init__(self):
        """Initialize the voice service with configurations from const.py"""
        try:
            # Initialize TTS configuration
            from nexent.core.models.tts_model import TTSConfig, TTSModel
            self.tts_config = TTSConfig(
                appid=APPID,
                token=TOKEN,
                cluster=CLUSTER,
                voice_type=VOICE_TYPE,
                speed_ratio=SPEED_RATIO
            )
            self.tts_model = TTSModel(self.tts_config)

        except Exception as e:
            logger.error(f"Failed to initialize voice service: {str(e)}")
            raise VoiceConfigException(f"Voice service initialization failed: {str(e)}") from e

    def _get_stt_model_from_config(
            self,
            tenant_id: Optional[str],
            model_factory: Optional[str] = None,
            model_name: Optional[str] = None,
            api_key: Optional[str] = None,
            model_appid: Optional[str] = None,
            access_token: Optional[str] = None,
            base_url: Optional[str] = None,
            language: str = "zh"
    ) -> BaseSTTModel:
        """
        Get the appropriate STT model based on model factory configuration.

        Args:
            tenant_id: Tenant ID for model lookup
            model_factory: Model factory/vendor name
            model_name: Model name
            api_key: API key (for Ali STT)
            model_appid: Application ID (for Volcano STT)
            access_token: Access token (for Volcano STT)
            base_url: Custom WebSocket URL (optional)
            language: Language for speech recognition

        Returns:
            STT model instance based on configuration
        """
        # Default to Ali Cloud if model_factory is not specified or is dashscope
        use_volc = model_factory and model_factory.lower() in ["volc", "volcano", "volcengine", "火山引擎"]

        if use_volc:
            # Use Volcano Engine STT
            logger.info(
                f"Using Volcano Engine STT with appid={model_appid}, access_token={'***' if access_token else None}")
            volc_config = VolcSTTConfig(
                appid=model_appid or "",
                access_token=access_token or "",
                ws_url=base_url if base_url else "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
                format="pcm",
                rate=16000
            )
            return VolcSTTModel(volc_config, TEST_PCM_PATH)
        else:
            # Use Ali Cloud STT (default)
            logger.info(f"Using Ali Cloud STT with api_key={'***' if api_key else None}")
            ali_config = AliSTTConfig(
                api_key=api_key or "",
                model=model_name or "qwen3-asr-flash-realtime",
                language=language,
                ws_url=base_url if base_url else None,
                format="pcm",
                rate=16000,
                enable_vad=True,
                timeout=5
            )
            return AliSTTModel(ali_config, TEST_PCM_PATH)

    def _get_stt_model_from_tenant_config(
            self,
            tenant_id: str,
            language: str = "zh"
    ) -> BaseSTTModel:
        """
        Get STT model based on tenant's model configuration.

        Args:
            tenant_id: Tenant ID
            language: Language for speech recognition

        Returns:
            STT model instance based on tenant's configuration
        """
        try:
            # Get STT model configuration from tenant config
            stt_config = tenant_config_manager.get_model_config(tenant_id, "stt")

            if stt_config:
                model_factory = stt_config.get("model_factory", "")
                model_name = stt_config.get("model_name", "")
                api_key = stt_config.get("api_key", "")
                base_url = stt_config.get("base_url", "")
                model_appid = stt_config.get("model_appid", "")
                access_token_val = stt_config.get("access_token", "")

                return self._get_stt_model_from_config(
                    tenant_id=tenant_id,
                    model_factory=model_factory,
                    model_name=model_name,
                    api_key=api_key,
                    model_appid=model_appid,
                    access_token=access_token_val,
                    base_url=base_url,
                    language=language
                )

            # Try to get from model records in database
            model_records = get_model_records({"model_type": "stt"}, tenant_id)
            if model_records:
                record = model_records[0]
                model_factory = record.get("model_factory", "")
                model_name = record.get("model_name", "")
                api_key = record.get("api_key", "")
                base_url = record.get("base_url", "")
                model_appid = record.get("model_appid", "")
                access_token_val = record.get("access_token", "")

                return self._get_stt_model_from_config(
                    tenant_id=tenant_id,
                    model_factory=model_factory,
                    model_name=model_name,
                    api_key=api_key,
                    model_appid=model_appid,
                    access_token=access_token_val,
                    base_url=base_url,
                    language=language
                )

            logger.warning(f"No STT model configuration found for tenant {tenant_id}, using default config")
            # Return default Ali STT model with empty config
            return self._get_stt_model_from_config(tenant_id=tenant_id, language=language)

        except Exception as e:
            logger.error(f"Error getting STT model config for tenant {tenant_id}: {str(e)}")
            # Return default on error
            return self._get_stt_model_from_config(tenant_id=tenant_id, language=language)

    async def start_stt_streaming_session(
            self,
            websocket,
            stt_config: Optional[Dict[str, Any]] = None,
            tenant_id: Optional[str] = None,
            language: str = "zh"
    ) -> None:
        """
        Start STT streaming session.

        Args:
            websocket: WebSocket connection for real-time audio streaming
            stt_config: STT configuration dict from client (preferred)
            tenant_id: Tenant ID for model lookup
            language: Language for speech recognition (default: zh)

        Raises:
            STTConnectionException: If STT streaming fails
        """
        try:
            # Extract config from stt_config dict if provided
            logger.info(f"Received stt_config: {stt_config}")

            model_factory = None
            model_name = None
            api_key = None
            model_appid = None
            access_token = None
            base_url = None

            if stt_config:
                model_factory = stt_config.get("model_factory")
                model_name = stt_config.get("model") or stt_config.get("model_name")
                api_key = stt_config.get("api_key") or stt_config.get("apiKey")
                model_appid = stt_config.get("model_appid") or stt_config.get("appid")
                access_token = stt_config.get("access_token")
                base_url = stt_config.get("base_url") or stt_config.get("baseUrl")
                language = stt_config.get("language", language)
                logger.info(
                    f"Extracted config - model_factory: {model_factory}, api_key: {'***' if api_key else None}, "
                    f"model_appid: {'***' if model_appid else None}, access_token: {'***' if access_token else None}")
            else:
                logger.warning("No stt_config provided, will use tenant model config if available")

            # Get STT model based on configuration
            if model_factory or api_key or model_appid:
                # Use explicit configuration from client
                stt_model = self._get_stt_model_from_config(
                    tenant_id=tenant_id,
                    model_factory=model_factory,
                    model_name=model_name,
                    api_key=api_key,
                    model_appid=model_appid,
                    access_token=access_token,
                    base_url=base_url,
                    language=language
                )
            elif tenant_id:
                # Use tenant's configured model
                stt_model = self._get_stt_model_from_tenant_config(tenant_id, language)
            else:
                # Use default Ali STT model
                logger.warning("No tenant_id provided and no explicit config, using default Ali STT")
                stt_model = self._get_stt_model_from_config(
                    tenant_id=tenant_id,
                    api_key=api_key,
                    language=language
                )

            await stt_model.start_streaming_session(websocket)
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

    async def check_stt_connectivity(
            self,
            model_factory: Optional[str] = None,
            api_key: Optional[str] = None,
            model_appid: Optional[str] = None,
            access_token: Optional[str] = None,
            language: str = "zh",
            model: str = "qwen3-asr-flash-realtime",
            base_url: Optional[str] = None
    ) -> bool:
        """
        Check STT service connectivity.

        Args:
            model_factory: Model factory/vendor name (e.g., "volc", "dashscope")
            api_key: API key for Ali STT
            model_appid: Application ID for Volcano STT
            access_token: Access token for Volcano STT
            language: Language for speech recognition (default: zh)
            model: STT model name (default: qwen3-asr-flash-realtime)
            base_url: Custom WebSocket URL (optional)

        Returns:
            bool: True if STT service is connected, False otherwise

        Raises:
            STTConnectionException: If connectivity check fails
        """
        try:
            # Get STT model based on factory
            stt_model = self._get_stt_model_from_config(
                tenant_id=None,
                model_factory=model_factory,
                model_name=model,
                api_key=api_key,
                model_appid=model_appid,
                access_token=access_token,
                base_url=base_url,
                language=language
            )

            logger.info(f"Checking STT connectivity for model factory: {model_factory}")
            connected = await stt_model.check_connectivity()

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

    async def check_voice_connectivity(
            self,
            model_type: str,
            stt_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Check voice service connectivity based on model type.

        Args:
            model_type: Type of model to check ('stt' or 'tts')
            stt_config: Optional STT configuration dict

        Returns:
            bool: True if the specified service is connected, False otherwise

        Raises:
            VoiceServiceException: If model_type is invalid
            STTConnectionException: If STT connectivity check fails
            TTSConnectionException: If TTS connectivity check fails
        """
        try:
            if model_type == 'stt':
                model_factory = stt_config.get("model_factory") if stt_config else None
                api_key = stt_config.get("api_key") if stt_config else None
                model_appid = stt_config.get("model_appid") if stt_config else None
                access_token = stt_config.get("access_token") if stt_config else None
                language = stt_config.get("language", "zh") if stt_config else "zh"
                model = stt_config.get("model",
                                       "qwen3-asr-flash-realtime") if stt_config else "qwen3-asr-flash-realtime"
                base_url = stt_config.get("base_url") if stt_config else None

                return await self.check_stt_connectivity(
                    model_factory=model_factory,
                    api_key=api_key,
                    model_appid=model_appid,
                    access_token=access_token,
                    language=language,
                    model=model,
                    base_url=base_url
                )
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
