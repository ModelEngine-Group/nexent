import asyncio
import logging
from http import HTTPStatus

from fastapi import APIRouter, WebSocket, HTTPException, Body, Query
from fastapi.responses import JSONResponse

from consts.exceptions import (
    VoiceServiceException,
    STTConnectionException,
    TTSConnectionException,
    VoiceConfigException
)
from consts.model import VoiceConnectivityRequest, VoiceConnectivityResponse
from services.voice_service import get_voice_service

logger = logging.getLogger("voice_app")

router = APIRouter(prefix="/voice")


@router.websocket("/stt/ws")
async def stt_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time audio streaming and STT"""
    logger.info("STT WebSocket connection attempt...")
    await websocket.accept()
    logger.info("STT WebSocket connection accepted")
    
    try:
        voice_service = get_voice_service()
        await voice_service.start_stt_streaming_session(websocket)
    except STTConnectionException as e:
        logger.error(f"STT WebSocket error: {str(e)}")
        await websocket.send_json({"error": str(e)})
    except Exception as e:
        logger.error(f"STT WebSocket error: {str(e)}")
        await websocket.send_json({"error": str(e)})
    finally:
        logger.info("STT WebSocket connection closed")


@router.websocket("/tts/ws")
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

        # Stream TTS audio to WebSocket
        voice_service = get_voice_service()
        await voice_service.stream_tts_to_websocket(websocket, text)

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


@router.post("/connectivity")
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
