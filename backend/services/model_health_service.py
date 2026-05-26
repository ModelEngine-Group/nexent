import logging
from typing import Optional
import httpx

from nexent.core import MessageObserver
from nexent.core.models import OpenAIModel, OpenAIVLModel
from nexent.core.models.embedding_model import JinaEmbedding, OpenAICompatibleEmbedding
from nexent.monitor import set_monitoring_context, set_monitoring_operation
from nexent.core.models.rerank_model import OpenAICompatibleRerank

from services.voice_service import get_voice_service
from consts.const import LOCALHOST_IP, LOCALHOST_NAME, DOCKER_INTERNAL_HOST
from consts.model import ModelConnectStatusEnum
from database.model_management_db import get_model_by_display_name, update_model_record
from utils.config_utils import get_model_name_from_config

logger = logging.getLogger("model_health_service")


def _mask_secret(value: Optional[str]) -> str:
    """Mask a secret value, showing only first and last 4 characters."""
    if not value or len(value) <= 8:
        return "***"
    return value[:4] + "****" + value[-4:]


async def _embedding_dimension_check(
    model_name: str,
    model_type: str,
    model_base_url: str,
    model_api_key: str,
    ssl_verify: bool = True,
    timeout_seconds: Optional[float] = None,
):
    # Test connectivity based on different model types
    if model_type == "embedding":
        embedding = await OpenAICompatibleEmbedding(
            model_name=model_name,
            base_url=model_base_url,
            api_key=model_api_key,
            embedding_dim=0,
            ssl_verify=ssl_verify,
            timeout_seconds=timeout_seconds,
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
            embedding_dim=0,
            ssl_verify=ssl_verify,
            timeout_seconds=timeout_seconds,
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
    ssl_verify: bool = True,
    model_factory: Optional[str] = None,
    model_appid: Optional[str] = None,
    access_token: Optional[str] = None,
    display_name: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
) -> bool:
    """
    Perform specific model connectivity check
    Args:
        model_name: Model name
        model_type: Model type
        model_base_url: Model base URL
        model_api_key: API key
        ssl_verify: Whether to verify SSL certificates (default: True)
        display_name: Optional display name for monitoring
        timeout_seconds: Optional request timeout in seconds
    Returns:
        bool: Connectivity check result
    """
    logger.info(f"Performing connectivity check for model={model_name} type={model_type} url={model_base_url}")
    
    if LOCALHOST_NAME in model_base_url or LOCALHOST_IP in model_base_url:
        model_base_url = model_base_url.replace(
            LOCALHOST_NAME, DOCKER_INTERNAL_HOST).replace(LOCALHOST_IP, DOCKER_INTERNAL_HOST)

    connectivity: bool

    # Test connectivity based on different model types
    if model_type == "embedding":
        embedding = OpenAICompatibleEmbedding(
            model_name=model_name,
            base_url=model_base_url,
            api_key=model_api_key,
            embedding_dim=0,
            ssl_verify=ssl_verify,
        )
        connectivity = len(await embedding.dimension_check(timeout=timeout_seconds if timeout_seconds else 5.0)) > 0
    elif model_type == "multi_embedding":
        embedding = JinaEmbedding(
            model_name=model_name,
            base_url=model_base_url,
            api_key=model_api_key,
            embedding_dim=0,
            ssl_verify=ssl_verify,
        )
        connectivity = len(await embedding.dimension_check(timeout=timeout_seconds if timeout_seconds else 5.0)) > 0
    elif model_type == "llm":
        observer = MessageObserver()
        set_monitoring_operation("connectivity_check",
                                 display_name=display_name)
        connectivity = await OpenAIModel(
            observer,
            model_id=model_name,
            api_base=model_base_url,
            api_key=model_api_key,
            ssl_verify=ssl_verify,
            timeout_seconds=timeout_seconds,
        ).check_connectivity()
    elif model_type == "rerank":
        rerank_model = OpenAICompatibleRerank(
            model_name=model_name,
            base_url=model_base_url,
            api_key=model_api_key,
            ssl_verify=ssl_verify,
        )
        connectivity = await rerank_model.connectivity_check()
    elif model_type in ("vlm", "image_understanding", "video_understanding"):
        # Vision/language models use OpenAIVLModel for connectivity check
        observer = MessageObserver()
        set_monitoring_operation("connectivity_check",
                                 display_name=display_name)
        connectivity = await OpenAIVLModel(
            observer,
            model_id=model_name,
            api_base=model_base_url,
            api_key=model_api_key,
            ssl_verify=ssl_verify
        ).check_connectivity()
    elif model_type == "image_generation":
        # Image generation models have a separate API endpoint
        # Use simple HTTP request to verify the API is accessible
        connectivity = False
        try:
            headers = {"Authorization": f"Bearer {model_api_key}"}
            async with httpx.AsyncClient(verify=ssl_verify, timeout=30) as client:
                # Test if the endpoint is reachable
                logger.info(f"Image generation connectivity check for model={model_name} url={model_base_url}")
                response = await client.post(
                    model_base_url,
                    headers=headers,
                    json={"model": model_name, "prompt": "test"}
                )
                logger.info(f"Image generation connectivity check response: status={response.status_code}")
                # Any response (even error) means the endpoint is reachable
                connectivity = response.status_code < 500
        except httpx.TimeoutException as e:
            logger.warning(f"Image generation connectivity check timeout for model={model_name} url={model_base_url}: {e}")
        except httpx.ConnectError as e:
            logger.warning(f"Image generation connectivity check failed (connect error) for model={model_name} url={model_base_url}: {e}")
        except Exception as e:
            logger.warning(f"Image generation connectivity check failed (exception) for model={model_name} url={model_base_url}: {type(e).__name__}: {e}")
    elif model_type in ["tts", "stt"]:
        voice_service = get_voice_service()


        # Determine STT provider based on model_factory
        use_volc = model_factory and model_factory.lower() in ["volcengine", "volcano", "volcengine", "火山引擎"]

        if use_volc:
            # Use Volcano STT with appid and access_token
            connectivity = await voice_service.check_voice_connectivity(
                model_type="stt",
                stt_config={
                    "model_factory": model_factory,
                    "model_appid": model_appid,
                    "access_token": access_token,
                    "base_url": model_base_url
                }
            )
        else:
            # Use Ali STT (default) with api_key and model name
            connectivity = await voice_service.check_voice_connectivity(
                model_type="stt",
                stt_config={
                    "api_key": model_api_key,
                    "base_url": model_base_url,
                    "model": model_name
                }
            )
    else:
        raise ValueError(f"Unsupported model type: {model_type}")

    return connectivity


async def check_model_connectivity(display_name: str, tenant_id: str) -> dict:
    try:
        # Query the database using display_name and tenant context from app layer
        model = get_model_by_display_name(display_name, tenant_id=tenant_id)
        if not model:
            raise LookupError(
                f"Model configuration not found for {display_name}")

        repo, name = model.get("model_repo", ""), model.get("model_name", "")
        model_name = f"{repo}/{name}" if repo else name

        update_data = {"connect_status": ModelConnectStatusEnum.DETECTING.value}
        update_model_record(model["model_id"], update_data)

        model_type = model["model_type"]
        model_base_url = model["base_url"]
        model_api_key = model["api_key"]
        # Default to True if not present
        ssl_verify = model.get("ssl_verify", True)
        model_factory = model.get("model_factory")
        model_appid = model.get("model_appid")
        access_token = model.get("access_token")
        timeout_seconds = model.get("timeout_seconds")

        try:
            set_monitoring_context(tenant_id=tenant_id)

            ssl_verify_fallback = False
            connectivity = await _perform_connectivity_check(
                model_name, model_type, model_base_url, model_api_key, ssl_verify,
                model_factory, model_appid, access_token, display_name, timeout_seconds,
            )
            if not connectivity and ssl_verify:
                ssl_verify_fallback = True
                connectivity = await _perform_connectivity_check(
                    model_name, model_type, model_base_url, model_api_key, False,
                    model_factory, model_appid, access_token, display_name, timeout_seconds,
                )
        except Exception as e:
            update_data = {
                "connect_status": ModelConnectStatusEnum.UNAVAILABLE.value}
            logger.error(f"Error checking model connectivity: {str(e)}")
            update_model_record(model["model_id"], update_data)
            raise e

        if connectivity:
            logger.info(
                f"CONNECTED: {model_name}")
        else:
            logger.warning(
                f"UNCONNECTED: {model_name}")
        connect_status = ModelConnectStatusEnum.AVAILABLE.value if connectivity else ModelConnectStatusEnum.UNAVAILABLE.value
        update_data = {"connect_status": connect_status}
        if ssl_verify_fallback:
            update_data["ssl_verify"] = False
        update_model_record(model["model_id"], update_data)
        return {
            "connectivity": connectivity,
            "model_name": model_name,
        }
    except Exception as e:
        logger.error(f"Error checking model connectivity: {str(e)}")
        if 'model' in locals() and model:
            update_data = {
                "connect_status": ModelConnectStatusEnum.UNAVAILABLE.value}
            update_model_record(model["model_id"], update_data)
        raise e




async def verify_model_config_connectivity(model_config: dict):
    """
    Verify the connectivity of the model configuration, do not save to the database.
    """
    try:
        model_name = model_config.get("model_name", "")
        model_type = model_config["model_type"]
        model_base_url = model_config.get("base_url", "")
        model_api_key = model_config["api_key"]
        # Default to True if not present
        ssl_verify = model_config.get("ssl_verify", True)
        model_factory = model_config.get("model_factory")
        model_appid = model_config.get("model_appid")
        access_token = model_config.get("access_token")
        # Get timeout from model config if present
        timeout_seconds = model_config.get("timeout_seconds")

        try:
            connectivity = await _perform_connectivity_check(
                model_name, model_type, model_base_url, model_api_key, ssl_verify,
                model_factory, model_appid, access_token, None, timeout_seconds,
            )
            if not connectivity and ssl_verify:
                connectivity = await _perform_connectivity_check(
                    model_name, model_type, model_base_url, model_api_key, False,
                    model_factory, model_appid, access_token, None, timeout_seconds,
                )
            if not connectivity:
                error_msg = f"Failed to connect to model '{model_name}' at {model_base_url}. Please verify the URL, API key, and network connection."
                return {
                    "connectivity": False,
                    "model_name": model_name,
                    "error": f"Failed to connect to model '{model_name}'. Please verify the URL, API key, and network connection."
                }

            return {
                "connectivity": True,
                "model_name": model_name,
            }
        except ValueError as e:
            error_msg = str(e)
            logger.warning(
                f"UNCONNECTED: {model_name}; Error: {error_msg}")
            return {
                "connectivity": False,
                "model_name": model_name,
                "error": error_msg
            }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to check connectivity of models: {error_msg}")
        return {
            "connectivity": False,
            "model_name": model_config.get("model_name", "UNKNOWN_MODEL"),
            "error": f"Connection verification failed: {error_msg}"
        }


async def embedding_dimension_check(model_config: dict):
    model_name = get_model_name_from_config(model_config)
    model_type = model_config["model_type"]
    model_base_url = model_config["base_url"]
    model_api_key = model_config["api_key"]

    try:
        ssl_verify = model_config.get("ssl_verify", True)
        timeout_seconds = model_config.get("timeout_seconds")
        dimension = await _embedding_dimension_check(
            model_name, model_type, model_base_url, model_api_key, ssl_verify,
            timeout_seconds=timeout_seconds
        )
        # Fallback to ssl_verify=False if initial check fails
        if dimension == 0 and ssl_verify:
            dimension = await _embedding_dimension_check(
                model_name, model_type, model_base_url, model_api_key, False,
                timeout_seconds=timeout_seconds
            )
        return dimension
    except ValueError as e:
        logger.error(f"Error checking embedding dimension: {str(e)}")
        return 0
    except Exception as e:
        logger.error(
            f"Error checking embedding dimension: {model_name};  Error: {str(e)}")
        return 0
