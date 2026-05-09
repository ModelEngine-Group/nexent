import logging
from http import HTTPStatus

from fastapi import APIRouter, WebSocket, HTTPException
from fastapi.responses import JSONResponse

from consts.exceptions import (
    VoiceServiceException,
    STTConnectionException,
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


@voice_config_router.post("/connectivity")
async def check_voice_connectivity(request: VoiceConnectivityRequest):
    """Check voice service connectivity."""
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
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except STTConnectionException as e:
        logger.error(f"Voice connectivity error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected voice service error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Voice service error")
