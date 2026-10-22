# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from http import HTTPStatus
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from contracts.errors.exceptions import VoiceServiceException, STTConnectionException, TTSConnectionException, VoiceConfigException
from contracts.voice import VoiceConnectivityRequest, VoiceConnectivityResponse
from management.services.model.voice import get_voice_service

logger = logging.getLogger("voice_app")


voice_config_router = APIRouter(prefix="/voice")


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
                message="Service is connected" if connected else "Service connection failed",
            ).dict(),
        )
    except VoiceServiceException as e:
        logger.error(f"Voice service error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except (STTConnectionException, TTSConnectionException) as e:
        logger.error(f"Voice connectivity error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=str(e))
    except VoiceConfigException as e:
        logger.error(f"Voice configuration error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected voice service error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Voice service error")
