import asyncio
import logging
from http import HTTPStatus

from fastapi import APIRouter, WebSocket, HTTPException
from fastapi.responses import JSONResponse

from consts.exceptions import (
    VoiceServiceException,
    STTConnectionException,
    TTSConnectionException,
    VoiceConfigException,
)
from consts.model import VoiceConnectivityRequest, VoiceConnectivityResponse
from services.voice_service import get_voice_service

logger = logging.getLogger("voice_app")

voice_runtime_router = APIRouter(prefix="/voice")
voice_config_router = APIRouter(prefix="/voice")


@voice_runtime_router.websocket("/stt/ws")
async def stt_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time audio streaming and STT"""
    logger.info("STT WebSocket connection attempt...")
    await websocket.accept()
    logger.info("STT WebSocket connection accepted")

    # Receive config from client
    client_config = {}
    try:
        msg = await websocket.receive()
        if msg["type"] == "websocket.receive":
            import json
            client_config = json.loads(msg["text"])
            logger.info(f"Received client config: {client_config}")
        elif msg["type"] == "bytes":
            try:
                import json
                client_config = json.loads(msg["bytes"].decode('utf-8'))
                logger.info(f"Received client config from bytes: {client_config}")
            except Exception as e:
                logger.warning(f"Failed to parse bytes as JSON: {e}")
    except Exception as e:
        logger.error(f"Error receiving config: {e}")
        client_config = {}

    try:
        voice_service = get_voice_service()
        await voice_service.start_stt_streaming_session(websocket, stt_config=client_config)
    except STTConnectionException as e:
        logger.error(f"STT WebSocket error: {str(e)}")
        await websocket.send_json({"error": str(e)})
    except Exception as e:
        logger.error(f"STT WebSocket error: {str(e)}")
        await websocket.send_json({"error": str(e)})
    finally:
        logger.info("STT WebSocket connection closed")


@voice_runtime_router.websocket("/tts/ws")
async def tts_websocket(websocket: WebSocket):
    """WebSocket endpoint for streaming TTS"""
    logger.info("TTS WebSocket connection attempt...")
    await websocket.accept()
    logger.info("TTS WebSocket connection accepted")

    try:
        # Receive config and text from client
        msg = await websocket.receive()
        client_config = {}
        text = None

        if msg["type"] == "websocket.receive":
            if "text" in msg:
                import json
                client_config = json.loads(msg["text"])
                text = client_config.get("text")
            elif "bytes" in msg:
                try:
                    import json
                    client_config = json.loads(msg["bytes"].decode('utf-8'))
                    text = client_config.get("text")
                except Exception as e:
                    logger.warning(f"Failed to parse bytes as JSON: {e}")

        if not text:
            if websocket.client_state.name == "CONNECTED":
                await websocket.send_json({"error": "No text provided"})
            return

        # Extract config from client
        tenant_id = client_config.get("tenant_id")
        model_factory = client_config.get("model_factory")
        model_name = client_config.get("model_name")
        api_key = client_config.get("api_key")
        model_appid = client_config.get("model_appid")
        access_token = client_config.get("access_token")
        base_url = client_config.get("base_url")

        logger.info(f"TTS request - model_name: {model_name}, model_factory: {model_factory}, "
                    f"has_api_key: {bool(api_key)}")

        # Build tts_config dict for voice service
        tts_config = {
            "model_factory": model_factory,
            "api_key": api_key,
            "model_appid": model_appid,
            "access_token": access_token,
            "base_url": base_url,
            "model_name": model_name,
        }

        # Stream TTS audio to WebSocket
        voice_service = get_voice_service()
        await voice_service.stream_tts_to_websocket(
            websocket,
            text,
            tenant_id=tenant_id,
            model_name=model_name,
            tts_config=tts_config
        )

    except TTSConnectionException as e:
        logger.error(f"TTS WebSocket error: {str(e)}")
        await websocket.send_json({"error": str(e)})
    except Exception as e:
        logger.error(f"TTS WebSocket error: {str(e)}")
        await websocket.send_json({"error": str(e)})
    finally:
        logger.info("TTS WebSocket connection closed")
        # Ensure connection is properly closed
        if websocket.client_state.name == "CONNECTED":
            await websocket.close()


@voice_config_router.post("/connectivity")
async def check_voice_connectivity(request: VoiceConnectivityRequest):
    """
    Check voice service connectivity

    Args:
        request: VoiceConnectivityRequest containing model_type

    Returns:
        VoiceConnectivityResponse with connectivity status
    """
    try:
        voice_service = get_voice_service()
        connected = await voice_service.check_voice_connectivity(request.model_type)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=VoiceConnectivityResponse(
                connected=connected,
                model_type=request.model_type,
                message="Service is connected" if connected else "Service connection failed"
            ).dict()
        )
    except VoiceServiceException as e:
        logger.error(f"Voice service error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(e)
        )
    except (STTConnectionException, TTSConnectionException) as e:
        logger.error(f"Voice connectivity error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except VoiceConfigException as e:
        logger.error(f"Voice configuration error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected voice service error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Voice service error"
        )
