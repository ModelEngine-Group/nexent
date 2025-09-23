import asyncio
import logging
import aiohttp
from http import HTTPStatus

from nexent.core import MessageObserver
from nexent.core.models import OpenAIModel, OpenAIVLModel
from nexent.core.models.embedding_model import JinaEmbedding, OpenAICompatibleEmbedding

from services.voice_service import get_voice_service
from consts.const import MODEL_ENGINE_APIKEY, MODEL_ENGINE_HOST, LOCALHOST_IP, LOCALHOST_NAME, DOCKER_INTERNAL_HOST
from consts.exceptions import MEConnectionException, TimeoutException
from consts.model import ModelConnectStatusEnum
from database.model_management_db import get_model_by_display_name, update_model_record
from utils.config_utils import get_model_name_from_config

logger = logging.getLogger("model_health_service")


async def _embedding_dimension_check(
    model_name: str,
    model_type: str,
    model_base_url: str,
    model_api_key: str
):
    # Test connectivity based on different model types
    if model_type == "embedding":
        embedding = await OpenAICompatibleEmbedding(
            model_name=model_name,
            base_url=model_base_url,
            api_key=model_api_key,
            embedding_dim=0
        ).dimension_check()
        if len(embedding) > 0:
            return len(embedding[0])
        logging.warning(
            f"Embedding dimension check for {model_name} gets empty response")
        return 0
    elif model_type == "multi_embedding":
        embedding = await JinaEmbedding(
            model_name=model_name,
            base_url=model_base_url,
            api_key=model_api_key,
            embedding_dim=0
        ).dimension_check()
        if len(embedding) > 0:
            return len(embedding[0])
        logging.warning(
            f"Embedding dimension check for {model_name} gets empty response")
        return 0
    else:
        raise ValueError(f"Unsupported model type: {model_type}")


async def _perform_connectivity_check(
    model_name: str,
    model_type: str,
    model_base_url: str,
    model_api_key: str,
) -> bool:
    """
    Perform specific model connectivity check
    Args:
        model_name: Model name
        model_type: Model type
        model_base_url: Model base URL
        model_api_key: API key
    Returns:
        bool: Connectivity check result
    """
    if LOCALHOST_NAME in model_base_url or LOCALHOST_IP in model_base_url:
        model_base_url = model_base_url.replace(
            LOCALHOST_NAME, DOCKER_INTERNAL_HOST).replace(LOCALHOST_IP, DOCKER_INTERNAL_HOST)

    connectivity: bool

    # Test connectivity based on different model types
    if model_type == "embedding":
        connectivity = len(await OpenAICompatibleEmbedding(
            model_name=model_name,
            base_url=model_base_url,
            api_key=model_api_key,
            embedding_dim=0
        ).dimension_check()) > 0
    elif model_type == "multi_embedding":
        connectivity = len(await JinaEmbedding(
            model_name=model_name,
            base_url=model_base_url,
            api_key=model_api_key,
            embedding_dim=0
        ).dimension_check()) > 0
    elif model_type == "llm":
        observer = MessageObserver()
        connectivity = await OpenAIModel(
            observer,
            model_id=model_name,
            api_base=model_base_url,
            api_key=model_api_key
        ).check_connectivity()
    elif model_type == "rerank":
        connectivity = False
    elif model_type == "vlm":
        observer = MessageObserver()
        connectivity = await OpenAIVLModel(
            observer,
            model_id=model_name,
            api_base=model_base_url,
            api_key=model_api_key
        ).check_connectivity()
    elif model_type in ["tts", "stt"]:
        voice_service = get_voice_service()
        connectivity = await voice_service.check_voice_connectivity(model_type)
    else:
        raise ValueError(f"Unsupported model type: {model_type}")

    return connectivity


async def check_model_connectivity(display_name: str, tenant_id: str) -> dict:
    try:
        # Query the database using display_name and tenant context from app layer
        model = get_model_by_display_name(display_name, tenant_id=tenant_id)
        if not model:
            raise LookupError(f"Model configuration not found for {display_name}")

        # Still use repo/name concatenation for model instantiation
        repo, name = model.get("model_repo", ""), model.get("model_name", "")
        model_name = f"{repo}/{name}" if repo else name

        # Set model to "detecting" status
        update_data = {
            "connect_status": ModelConnectStatusEnum.DETECTING.value}
        update_model_record(model["model_id"], update_data)

        model_type = model["model_type"]
        model_base_url = model["base_url"]
        model_api_key = model["api_key"]

        try:
            # Use the common connectivity check function
            connectivity = await _perform_connectivity_check(
                model_name, model_type, model_base_url, model_api_key
            )
        except Exception as e:
            update_data = {"connect_status": ModelConnectStatusEnum.UNAVAILABLE.value}
            logger.error(f"Error checking model connectivity: {str(e)}")
            update_model_record(model["model_id"], update_data)
            raise e

        if connectivity:
            logger.info(f"CONNECTED: {model_name}; Base URL: {model.get('base_url')}; API Key: {model.get('api_key')}")
        else:
            logger.warning(f"UNCONNECTED: {model_name}; Base URL: {model.get('base_url')}; API Key: {model.get('api_key')}")
        connect_status = ModelConnectStatusEnum.AVAILABLE.value if connectivity else ModelConnectStatusEnum.UNAVAILABLE.value
        update_data = {"connect_status": connect_status}
        update_model_record(model["model_id"], update_data)
        return {
            "connectivity": connectivity,
            "model_name": model_name,
        }
    except Exception as e:
        logger.error(f"Error checking model connectivity: {str(e)}")
        if 'model' in locals() and model:
            update_data = {"connect_status": ModelConnectStatusEnum.UNAVAILABLE.value}
            update_model_record(model["model_id"], update_data)
        # Propagate for app layer to translate into HTTP
        raise e


async def check_me_connectivity_impl(timeout: int):
    """
    Check ME connectivity and return structured response data
    Args:
        timeout: Request timeout in seconds
    """
    try:
        headers = {'Authorization': f'Bearer {MODEL_ENGINE_APIKEY}'}

        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout),
                connector=aiohttp.TCPConnector(ssl=False)
        ) as session:
            async with session.get(
                    f"{MODEL_ENGINE_HOST}/open/router/v1/models",
                    headers=headers
            ) as response:
                if response.status == HTTPStatus.OK:
                    return
                else:
                    raise MEConnectionException(
                        f"Connection failed, error code: {response.status}")
    except asyncio.TimeoutError:
        raise TimeoutException("Connection timed out")
    except Exception as e:
        raise Exception(f"Unknown error occurred: {str(e)}")


async def verify_model_config_connectivity(model_config: dict):
    """
    Verify the connectivity of the model configuration, do not save to the database
    Args:
        model_config: Model configuration dictionary, containing necessary connection parameters
    Returns:
        dict: Contains the result of the connectivity test
    """
    try:
        model_name = model_config.get("model_name", "")
        model_type = model_config["model_type"]
        model_base_url = model_config["base_url"]
        model_api_key = model_config["api_key"]

        try:
            # Use the common connectivity check function
            connectivity = await _perform_connectivity_check(
                model_name, model_type, model_base_url, model_api_key
            )
        except ValueError as e:
            logger.warning(f"UNCONNECTED: {model_name}; Base URL: {model_base_url}; API Key: {model_api_key}; Error: {str(e)}")
            return {
                "connectivity": False,
                "model_name": model_name
            }

        return {
            "connectivity": connectivity,
            "model_name": model_name,
        }

    except Exception as e:
        logger.error(f"Failed to check connectivity of models: {str(e)}")
        return {
            "connectivity": False,
            "model_name": model_config.get("model_name", "UNKNOWN_MODEL")
        }


async def embedding_dimension_check(model_config: dict):
    model_name = get_model_name_from_config(model_config)
    model_type = model_config["model_type"]
    model_base_url = model_config["base_url"]
    model_api_key = model_config["api_key"]

    try:
        dimension = await _embedding_dimension_check(
            model_name, model_type, model_base_url, model_api_key
        )
        return dimension
    except ValueError as e:
        logger.error(f"Error checking embedding dimension: {str(e)}")
        return 0
    except Exception as e:
        logger.error(f"Error checking embedding dimension: {model_name}; Base URL: {model_base_url}; Error: {str(e)}")
        return 0
