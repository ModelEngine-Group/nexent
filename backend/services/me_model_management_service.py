import aiohttp
import asyncio

from consts.const import MODEL_ENGINE_HOST, MODEL_ENGINE_API_KEY
from consts.exceptions import MEConnectionException, TimeoutException


async def check_me_variable_set() -> bool:
    """
    Check if the ME environment variables are correctly set.
    Returns:
        bool: True if MODEL_ENGINE_HOST are set and non-empty, False otherwise.
    """
    return bool(MODEL_ENGINE_HOST)


async def check_me_connectivity(timeout: int = 30) -> bool:
    """
    Check ModelEngine connectivity by actually calling the API.

    Args:
        timeout: Request timeout in seconds

    Returns:
        bool: True if connection successful, False otherwise

    Raises:
        MEConnectionException: If connection failed with specific error
        TimeoutException: If request timed out
    """
    if not await check_me_variable_set():
        return False

    try:
        headers = {"Authorization": f"Bearer {MODEL_ENGINE_API_KEY}"}

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout),
            connector=aiohttp.TCPConnector(ssl=False)
        ) as session:
            async with session.get(
                f"{MODEL_ENGINE_HOST}/open/router/v1/models",
                headers=headers
            ) as response:
                if response.status == 200:
                    return True
                else:
                    raise MEConnectionException(
                        f"Connection failed, error code: {response.status}")
    except asyncio.TimeoutError:
        raise TimeoutException("Connection timed out")
    except MEConnectionException:
        raise
    except Exception as e:
        raise Exception(f"Unknown error occurred: {str(e)}")
