import logging
from typing import Any, Dict, Optional

from nexent.core.models.stt_model import BaseSTTModel
from nexent.core.models.volc_stt_model import VolcSTTConfig, VolcSTTModel
from nexent.core.models.ali_stt_model import AliSTTConfig, AliSTTModel

from consts.const import TEST_PCM_PATH
from consts.exceptions import (
    VoiceServiceException,
    STTConnectionException,
)
from database.model_management_db import get_model_records
from utils.config_utils import tenant_config_manager

logger = logging.getLogger("voice_service")


class VoiceService:
    """Voice service that handles STT operations"""

    def _get_stt_model_from_config(
        self,
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
        use_volc = model_factory and model_factory.lower() in ["volc", "volcano", "volcengine", "火山引擎"]

        if use_volc:
            volc_config = VolcSTTConfig(
                appid=model_appid or "",
                access_token=access_token or "",
                ws_url=base_url if base_url else "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
                format="pcm",
                rate=16000
            )
            return VolcSTTModel(volc_config, TEST_PCM_PATH)
        else:
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
            stt_config = tenant_config_manager.get_model_config(tenant_id, "stt")

            if stt_config:
                model_factory = stt_config.get("model_factory", "")
                model_name = stt_config.get("model_name", "")
                api_key = stt_config.get("api_key", "")
                base_url = stt_config.get("base_url", "")
                model_appid = stt_config.get("model_appid", "")
                access_token_val = stt_config.get("access_token", "")

                return self._get_stt_model_from_config(
                    model_factory=model_factory,
                    model_name=model_name,
                    api_key=api_key,
                    model_appid=model_appid,
                    access_token=access_token_val,
                    base_url=base_url,
                    language=language
                )

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
                    model_factory=model_factory,
                    model_name=model_name,
                    api_key=api_key,
                    model_appid=model_appid,
                    access_token=access_token_val,
                    base_url=base_url,
                    language=language
                )

            logger.warning(f"No STT model configuration found for tenant {tenant_id}, using default config")
            return self._get_stt_model_from_config(language=language)

        except Exception as e:
            logger.error(f"Error getting STT model config for tenant {tenant_id}: {str(e)}")
            return self._get_stt_model_from_config(language=language)

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
            else:
                logger.warning("No stt_config provided, will use tenant model config if available")

            if model_factory or api_key or model_appid:
                stt_model = self._get_stt_model_from_config(
                    model_factory=model_factory,
                    model_name=model_name,
                    api_key=api_key,
                    model_appid=model_appid,
                    access_token=access_token,
                    base_url=base_url,
                    language=language
                )
            elif tenant_id:
                stt_model = self._get_stt_model_from_tenant_config(tenant_id, language)
            else:
                logger.warning("No tenant_id provided and no explicit config, using default Ali STT")
                stt_model = self._get_stt_model_from_config(
                    api_key=api_key,
                    language=language
                )

            await stt_model.start_streaming_session(websocket)
        except Exception as e:
            logger.error(f"STT streaming session failed: {str(e)}")
            raise STTConnectionException(f"STT streaming failed: {str(e)}") from e

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
            stt_model = self._get_stt_model_from_config(
                model_factory=model_factory,
                model_name=model,
                api_key=api_key,
                model_appid=model_appid,
                access_token=access_token,
                base_url=base_url,
                language=language
            )

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

    async def check_voice_connectivity(
        self,
        model_type: str,
        stt_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Check voice service connectivity based on model type.

        Args:
            model_type: Type of model to check ('stt' only)
            stt_config: Optional STT configuration dict

        Returns:
            bool: True if the service is connected, False otherwise

        Raises:
            VoiceServiceException: If model_type is invalid
            STTConnectionException: If STT connectivity check fails
        """
        if model_type != "stt":
            logger.error(f"Unsupported model type: {model_type}")
            raise VoiceServiceException(f"Unsupported model type: {model_type}")

        try:
            model_factory = stt_config.get("model_factory") if stt_config else None
            api_key = stt_config.get("api_key") if stt_config else None
            model_appid = stt_config.get("model_appid") if stt_config else None
            access_token = stt_config.get("access_token") if stt_config else None
            language = stt_config.get("language", "zh") if stt_config else "zh"
            model = stt_config.get("model", "qwen3-asr-flash-realtime") if stt_config else "qwen3-asr-flash-realtime"
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
        except STTConnectionException:
            raise
        except Exception as e:
            logger.error(f"Voice service connectivity check failed: {str(e)}")
            raise VoiceServiceException(f"Voice service connectivity check failed: {str(e)}") from e


# Global voice service instance
_voice_service_instance: Optional[VoiceService] = None


def get_voice_service() -> VoiceService:
    """Get the global voice service instance."""
    global _voice_service_instance
    if _voice_service_instance is None:
        _voice_service_instance = VoiceService()
    return _voice_service_instance
