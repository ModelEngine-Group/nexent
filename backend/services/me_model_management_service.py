import asyncio
from typing import List, Dict

import aiohttp
from onnx.reference.ops.op_optional import Optional

from consts.const import MODEL_ENGINE_APIKEY, MODEL_ENGINE_HOST
from consts.exceptions import TimeoutException


async def get_me_models_impl(timeout: int = 2, type: Optional[str] = None) -> List[Dict]:
    """
    Fetches a list of models from the model engine API, optionally filtering by type.
    Parameters:
        timeout (float): The total timeout for the request in seconds.
        type (str or None): The type of model to filter for. If None, returns all models.
    Returns:
        list: A list of model data dictionaries, filtered by the specified type if provided.
    Raises:
        TimeoutException: If the request times out.
        Exception: If no models of the specified type are found, or if another request error occurs.
    """
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
                raise Exception(
                    f"No models found with type '{type}'. Available types: {result_types}.")
        else:
            filtered_result = result
        return filtered_result
    except asyncio.TimeoutError:
        raise TimeoutException("Request timeout.")
    except Exception as e:
        raise Exception(f"Request error: {e}.")
