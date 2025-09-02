import asyncio

import aiohttp
from fastapi import APIRouter, Query

from consts.const import MODEL_ENGINE_APIKEY, MODEL_ENGINE_HOST
from consts.model import ModelConnectStatusEnum, ModelResponse
from services.model_health_service import check_me_model_connectivity

router = APIRouter(prefix="/me")


@router.get("/model/list", response_model=ModelResponse)
async def get_me_models(
        type: str = Query(
            default="", description="Model type: embed/chat/rerank"),
        timeout: int = Query(
            default=2, description="Request timeout in seconds")
):
    try:
        headers = {
            'Authorization': f'Bearer {MODEL_ENGINE_APIKEY}',
        }

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout),
            connector=aiohttp.TCPConnector(verify_ssl=False)
        ) as session:
            async with session.get(
                f"{MODEL_ENGINE_HOST}/open/router/v1/models",
                headers=headers
            ) as response:
                response.raise_for_status()
                result_data = await response.json()
                result: list = result_data['data']

        # Type filtering
        filtered_result = []
        if type:
            for data in result:
                if data['type'] == type:
                    filtered_result.append(data)
            if not filtered_result:
                result_types = set(data['type'] for data in result)
                return ModelResponse(
                    code=404,
                    message=f"No models found with type '{type}'. Available types: {result_types}",
                    data=[]
                )
        else:
            filtered_result = result

        return ModelResponse(
            code=200,
            message="Successfully retrieved",
            data=filtered_result
        )

    except asyncio.TimeoutError:
        return ModelResponse(
            code=408,
            message="Request timeout",
            data=[]
        )
    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Failed to get model list: {str(e)}",
            data=[]
        )


@router.get("/healthcheck", response_model=ModelResponse)
async def check_me_connectivity(timeout: int = Query(default=2, description="Timeout in seconds")):
    try:
        headers = {'Authorization': f'Bearer {MODEL_ENGINE_APIKEY}'}

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout),
            connector=aiohttp.TCPConnector(ssl=False)
        ) as session:
            try:
                async with session.get(
                    f"{MODEL_ENGINE_HOST}/open/router/v1/models",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        return ModelResponse(
                            code=200,
                            message="Connection successful",
                            data={"status": "Connected", "desc": "Connection successful",
                                  "connect_status": ModelConnectStatusEnum.AVAILABLE.value}
                        )
                    else:
                        return ModelResponse(
                            code=response.status,
                            message=f"Connection failed, error code: {response.status}",
                            data={"status": "Disconnected", "desc": f"Connection failed, error code: {response.status}",
                                  "connect_status": ModelConnectStatusEnum.UNAVAILABLE.value}
                        )
            except asyncio.TimeoutError:
                return ModelResponse(
                    code=408,
                    message="Connection timeout",
                    data={"status": "Disconnected", "desc": "Connection timeout",
                          "connect_status": ModelConnectStatusEnum.UNAVAILABLE.value}
                )

    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Unknown error occurred: {str(e)}",
            data={"status": "Disconnected", "desc": f"Unknown error occurred: {str(e)}",
                  "connect_status": ModelConnectStatusEnum.UNAVAILABLE.value}
        )


@router.get("/model/healthcheck", response_model=ModelResponse)
async def check_me_model_healthcheck(
        model_name: str = Query(..., description="Model name to check")
):
    return await check_me_model_connectivity(model_name)
