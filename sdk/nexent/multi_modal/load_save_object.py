import functools
import inspect
import logging
from io import BytesIO
from typing import Any, Callable, List, Optional, Tuple
import requests

from .utils import (
    UrlType,
    is_url,
    generate_object_name,
    detect_content_type_from_bytes,
    guess_extension_from_content_type,
    parse_s3_url
)

logger = logging.getLogger("multi_modal")


class LoadSaveObjectManager:
    """
    Provide load/save decorators that operate on a specific storage client.
    
    The manager can be instantiated with a storage client and exposes decorator
    factories for `load_object` and `save_object`. A default module-level manager
    is also provided for backwards compatibility with existing helper functions.
    """

    def __init__(self, storage_client: Any):
        self._storage_client = storage_client

    def _get_client(self) -> Any:
        """
        Return a ready-to-use storage client, ensuring initialization first.
        """
        if self._storage_client is None:
            raise ValueError("Storage client is not initialized.")
        return self._storage_client

    def download_file_from_url(
            self,
            url: str,
            url_type: UrlType,
            timeout: int = 30
    ) -> Optional[bytes]:
        """
        Download file content from S3 URL or HTTP/HTTPS URL as bytes.
        """
        if not url:
            return None

        if not url_type:
            raise ValueError("url_type must be provided for download_file_from_url")

        try:
            if url_type in ("http", "https"):
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()
                return response.content

            if url_type == "s3":
                client = self._get_client()
                bucket, object_name = parse_s3_url(url)

                if not hasattr(client, 'get_file_stream'):
                    raise ValueError("Storage client does not have get_file_stream method")

                success, stream = client.get_file_stream(object_name, bucket)
                if not success:
                    raise ValueError(f"Failed to get file stream from storage: {stream}")

                try:
                    bytes_data = stream.read()
                    if hasattr(stream, 'close'):
                        stream.close()
                    return bytes_data
                except Exception as exc:
                    raise ValueError(f"Failed to read stream content: {exc}") from exc

            raise ValueError(f"Unsupported URL type: {url_type}")

        except Exception as exc:
            logger.error(f"Failed to download file from URL: {exc}")
            return None

    def _upload_bytes_to_minio(
            self,
            bytes_data: bytes,
            object_name: Optional[str] = None,
            bucket: str = "nexent",
            content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload bytes to MinIO and return the resulting file URL.
        """
        client = self._get_client()

        if not hasattr(client, 'upload_fileobj'):
            raise ValueError("Storage client must have upload_fileobj method")

        if object_name is None:
            file_ext = guess_extension_from_content_type(content_type)
            object_name = generate_object_name(file_ext)

        file_obj = BytesIO(bytes_data)
        success, result = client.upload_fileobj(file_obj, object_name, bucket)

        if not success:
            raise ValueError(f"Failed to upload file to MinIO: {result}")

        return result

    def load_object(
            self,
            input_names: List[str],
            input_data_transformer: Optional[List[Callable[[bytes], Any]]] = None,
    ):
        """
        Decorator factory that downloads inputs before invoking the wrapped callable.
        """

        def decorator(func: Callable):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                def _transform_single_value(param_name: str, value: Any,
                                            transformer: Optional[Callable[[bytes], Any]]) -> Any:
                    if isinstance(value, str):
                        url_type = is_url(value)
                        if url_type:
                            bytes_data = self.download_file_from_url(value, url_type=url_type)

                            if bytes_data is None:
                                raise ValueError(f"Failed to download file from URL: {value}")

                            if transformer:
                                transformed_data = transformer(bytes_data)
                                logger.info(
                                    f"Downloaded {param_name} from URL and transformed "
                                    f"using {transformer.__name__}"
                                )
                                return transformed_data

                            logger.info(f"Downloaded {param_name} from URL as bytes (binary stream)")
                            return bytes_data

                    raise ValueError(
                        f"Parameter '{param_name}' is not a URL string. "
                        f"load_object decorator expects S3 or HTTP/HTTPS URLs. "
                        f"Got: {type(value).__name__}"
                    )

                def _process_value(param_name: str, value: Any,
                                   transformer: Optional[Callable[[bytes], Any]]) -> Any:
                    if value is None:
                        return None

                    if isinstance(value, (list, tuple)):
                        processed_items = [
                            _process_value(param_name, item, transformer)
                            for item in value
                        ]
                        return type(value)(processed_items)

                    return _transform_single_value(param_name, value, transformer)

                sig = inspect.signature(func)
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()

                for i, param_name in enumerate(input_names):
                    if param_name not in bound_args.arguments:
                        continue

                    original_data = bound_args.arguments[param_name]
                    if original_data is None:
                        continue

                    transformer_func = (
                        input_data_transformer[i]
                        if input_data_transformer and i < len(input_data_transformer)
                        else None
                    )

                    transformed_data = _process_value(param_name, original_data, transformer_func)
                    bound_args.arguments[param_name] = transformed_data

                return func(*bound_args.args, **bound_args.kwargs)

            return wrapper

        return decorator

    def save_object(
            self,
            output_names: List[str],
            output_transformers: Optional[List[Callable[[Any], bytes]]] = None,
            bucket: str = "nexent",
    ):
        """
        Decorator factory that uploads outputs to storage after function execution.
        """

        def decorator(func: Callable) -> Callable:
            def _handle_results(results: Any):
                if not isinstance(results, tuple):
                    results_tuple = (results,)
                else:
                    results_tuple = results

                if len(results_tuple) != len(output_names):
                    raise ValueError(
                        f"Function returned {len(results_tuple)} values, "
                        f"but expected {len(output_names)} outputs"
                    )

                def _upload_single_output(
                        name: str,
                        value: Any,
                        transformer: Optional[Callable[[Any], bytes]]
                ) -> str:
                    if transformer:
                        bytes_data = transformer(value)
                        if not isinstance(bytes_data, bytes):
                            raise ValueError(
                                f"Transformer {transformer.__name__} for {name} must return bytes, "
                                f"got {type(bytes_data).__name__}"
                            )
                        logger.info(f"Transformed {name} using {transformer.__name__} to bytes")
                    else:
                        if not isinstance(value, bytes):
                            raise ValueError(
                                f"Return value for {name} must be bytes when no transformer is provided, "
                                f"got {type(value).__name__}"
                            )
                        bytes_data = value
                        logger.info(f"Using {name} as bytes directly")

                    content_type = detect_content_type_from_bytes(bytes_data)
                    logger.info(f"Detected content type for {name}: {content_type}")

                    file_url = self._upload_bytes_to_minio(
                        bytes_data,
                        object_name=None,
                        content_type=content_type,
                        bucket=bucket,
                    )
                    logger.info(f"Uploaded {name} to MinIO: {file_url}")
                    return "s3:/" + file_url

                def _process_output_value(
                        name: str,
                        value: Any,
                        transformer: Optional[Callable[[Any], bytes]]
                ) -> Any:
                    if value is None:
                        return None

                    if isinstance(value, (list, tuple)):
                        processed_items = [
                            _process_output_value(name, item, transformer)
                            for item in value
                        ]
                        return type(value)(processed_items)

                    return _upload_single_output(name, value, transformer)

                uploaded_urls = []
                for i, (result, name) in enumerate(zip(results_tuple, output_names)):
                    transformer_func = (
                        output_transformers[i]
                        if output_transformers and i < len(output_transformers)
                        else None
                    )
                    processed_result = _process_output_value(name, result, transformer_func)
                    uploaded_urls.append(processed_result)

                if len(uploaded_urls) == 1:
                    return uploaded_urls[0]
                return tuple(uploaded_urls)

            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    results = await func(*args, **kwargs)
                    return _handle_results(results)

                return async_wrapper

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                results = func(*args, **kwargs)
                return _handle_results(results)

            return wrapper

        return decorator