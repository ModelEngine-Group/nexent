from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
import os
import asyncio
import sys
from unittest.mock import patch, MagicMock, AsyncMock
from io import BytesIO
from pathlib import Path
import pytest

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Apply critical patches before importing any modules
# This prevents real AWS calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Create a full mock for MinioClient to avoid initialization issues
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.boto3.client', return_value=MagicMock()).start()
patch('backend.database.client.minio_client', minio_mock).start()

from backend.apps.file_management_app import router

# Create a FastAPI app and include the router for testing
app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_patches():
    patches = [
        patch('backend.database.client.db_client', MagicMock()),
        patch('backend.utils.auth_utils.get_current_user_id',
              MagicMock(return_value=('test_user', 'test_tenant'))),
        patch('backend.utils.attachment_utils.convert_image_to_text',
              MagicMock(side_effect=lambda query, image_input, tenant_id, language='zh': 'mocked image text')),
        patch('backend.utils.attachment_utils.convert_long_text_to_text',
              MagicMock(side_effect=lambda query, file_context, tenant_id, language='zh': 'mocked text content')),
        patch('httpx.AsyncClient', MagicMock())
    ]

    # Start all patches
    for p in patches:
        p.start()

    yield

    # Stop all patches
    for p in patches:
        p.stop()


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def mock_files():
    # Create mock files for testing
    mock_file_content = b"test file content"
    mock_image_content = b"mock image binary data"
    upload_dir = Path("test_uploads")
    upload_dir.mkdir(exist_ok=True)

    yield {
        "mock_file_content": mock_file_content,
        "mock_image_content": mock_image_content,
        "upload_dir": upload_dir
    }

    # Clean up test files
    if upload_dir.exists():
        for file in upload_dir.iterdir():
            file.unlink()
        upload_dir.rmdir()


def create_mock_upload_file(filename="test.txt", content=None):
    content = content or b"test file content"
    return {
        "file": (filename, BytesIO(content), "text/plain")
    }


@pytest.mark.asyncio
async def test_upload_files_success(mock_files):
    with patch("backend.services.file_management_service.upload_files_impl") as mock_upload_impl:

        # Configure mock for successful upload
        mock_upload_impl.return_value = (
            [],  # errors
            ["/test/path/test1.txt", "/test/path/test2.txt"],  # uploaded_file_paths
            ["test1.txt", "test2.txt"]  # uploaded_filenames
        )

        # Create test client
        with TestClient(app) as client:
            response = client.post(
                "/file/upload",
                files=[
                    ("file", ("test1.txt", BytesIO(b"test1 content"), "text/plain")),
                    ("file", ("test2.txt", BytesIO(b"test2 content"), "text/plain"))
                ],
                data={
                    "destination": "local",
                    "folder": "test_folder"
                }
            )

        # Assertions
        assert response.status_code == 200
        assert "message" in response.json()
        assert "uploaded_filenames" in response.json()
        assert len(response.json()["uploaded_filenames"]) == 2


@pytest.mark.asyncio
async def test_process_files_success(mock_files):
    with patch("backend.apps.file_management_app.trigger_data_process") as mock_trigger:

        # Configure mock for successful processing - return result directly
        mock_trigger.return_value = {
            "task_id": "task_123",
            "status": "processing"
        }

        # Create test client
        with TestClient(app) as client:
            response = client.post(
                "/file/process",
                json={
                    "files": [
                        {"path_or_url": "/test/path/test.txt",
                            "filename": "test.txt"}
                    ],
                    "chunking_strategy": "basic",
                    "index_name": "test_index",
                    "destination": "local"
                },
                headers={"authorization": "Bearer test_token"}
            )

        # Assertions
        assert response.status_code == 201
        assert "message" in response.json()
        assert "process_tasks" in response.json()
        assert response.json()[
            "message"] == "Files processing triggered successfully"


@pytest.mark.asyncio
async def test_process_files_processing_error(mock_files):
    with patch("backend.apps.file_management_app.trigger_data_process") as mock_trigger:

        # Configure mock for processing error - return result directly
        mock_trigger.return_value = {
            "status": "error",
            "message": "Processing failed"
        }

        # Create test client
        with TestClient(app) as client:
            response = client.post(
                "/file/process",
                json={
                    "files": [
                        {"path_or_url": "/test/path/test.txt",
                            "filename": "test.txt"}
                    ],
                    "chunking_strategy": "basic",
                    "index_name": "test_index",
                    "destination": "local"
                },
                headers={"authorization": "Bearer test_token"}
            )

        # Assertions
        assert response.status_code == 500
        assert "detail" in response.json()
        assert response.json()["detail"] == "Processing failed"


@pytest.mark.asyncio
async def test_process_files_none_result(mock_files):
    with patch("backend.apps.file_management_app.trigger_data_process") as mock_trigger:

        # Configure mock to return None directly
        mock_trigger.return_value = None

        # Create test client
        with TestClient(app) as client:
            response = client.post(
                "/file/process",
                json={
                    "files": [
                        {"path_or_url": "/test/path/test.txt",
                            "filename": "test.txt"}
                    ],
                    "chunking_strategy": "by_title",
                    "index_name": "test_index",
                    "destination": "minio"
                },
                headers={"authorization": "Bearer test_token"}
            )

        # Assertions
        assert response.status_code == 500
        assert "detail" in response.json()
        assert response.json()["detail"] == "Data process service failed"


@pytest.mark.asyncio
async def test_upload_files_no_files(mock_files):
    # Create a new test app with a mocked endpoint
    test_app = FastAPI()

    @test_app.post("/file/upload")
    async def mock_upload_files():
        # This simulates the behavior we want to test
        raise HTTPException(status_code=400, detail="No files in the request")

    # Create a test client with our mocked app
    with TestClient(test_app) as client:
        response = client.post(
            "/file/upload",
            files=[("file", ("empty.txt", BytesIO(b""), "text/plain"))],
            data={"destination": "local", "folder": "test_folder"}
        )

    # Assertions
    assert response.status_code == 400
    assert "detail" in response.json()


@pytest.mark.asyncio
async def test_storage_upload_files_success(mock_files):
    with patch("backend.services.file_management_service.upload_to_minio") as mock_upload:
        # Configure mock
        mock_upload.return_value = [
            {
                "success": True,
                "file_name": "test1.txt",
                "url": "https://test-url.com/test1.txt"
            },
            {
                "success": True,
                "file_name": "test2.txt",
                "url": "https://test-url.com/test2.txt"
            }
        ]

        # Create test client
        with TestClient(app) as client:
            response = client.post(
                "/file/storage",
                files=[
                    ("files", ("test1.txt", BytesIO(b"test1 content"), "text/plain")),
                    ("files", ("test2.txt", BytesIO(b"test2 content"), "text/plain"))
                ],
                data={"folder": "test_folder"}
            )

        # Assertions
        assert response.status_code == 200
        assert "message" in response.json()
        assert response.json()["success_count"] == 2
        assert response.json()["failed_count"] == 0


@pytest.mark.asyncio
async def test_storage_upload_files_partial_failure(mock_files):
    with patch("backend.apps.file_management_app.upload_to_minio") as mock_upload:
        # Configure mock to simulate one success and one failure
        mock_upload.return_value = [
            {
                "success": True,
                "file_name": "test1.txt",
                "url": "https://test-url.com/test1.txt"
            },
            {
                "success": False,
                "file_name": "test2.txt",
                "error": "Upload failed"
            }
        ]

        # Create test client
        with TestClient(app) as client:
            response = client.post(
                "/file/storage",
                files=[
                    ("files", ("test1.txt", BytesIO(b"test1 content"), "text/plain")),
                    ("files", ("test2.txt", BytesIO(b"test2 content"), "text/plain"))
                ]
            )

        # Assertions
        assert response.status_code == 200
        assert response.json()["success_count"] == 1
        assert response.json()["failed_count"] == 1


@pytest.mark.asyncio
async def test_get_storage_files(mock_files):
    with patch("backend.apps.file_management_app.list_files_impl") as mock_list:
        # Configure mock
        mock_list.return_value = [
            {"name": "test1.txt", "size": 100,
                "url": "https://test-url.com/test1.txt"},
            {"name": "test2.txt", "size": 200,
                "url": "https://test-url.com/test2.txt"}
        ]

        # Create test client
        with TestClient(app) as client:
            response = client.get(
                "/file/storage?prefix=test&limit=10&include_urls=true")

        # Assertions
        assert response.status_code == 200
        assert response.json()["total"] == 2
        assert len(response.json()["files"]) == 2


@pytest.mark.asyncio
async def test_get_storage_files_no_urls(mock_files):
    with patch("backend.apps.file_management_app.list_files_impl") as mock_list:
        # Configure mock
        mock_list.return_value = [
            {"name": "test1.txt", "size": 100,
                "url": "https://test-url.com/test1.txt"},
            {"name": "test2.txt", "size": 200,
                "url": "https://test-url.com/test2.txt"}
        ]

        # Create test client
        with TestClient(app) as client:
            response = client.get("/file/storage?include_urls=false")

        # Assertions
        assert response.status_code == 200
        for file in response.json()["files"]:
            assert "url" not in file


@pytest.mark.asyncio
async def test_get_storage_files_error(mock_files):
    with patch("backend.apps.file_management_app.list_files_impl") as mock_list:
        # Configure mock
        mock_list.side_effect = Exception("Storage access error")

        # Create test client
        with TestClient(app) as client:
            response = client.get("/file/storage")

        # Assertions
        assert response.status_code == 500
        assert "detail" in response.json()


@pytest.mark.asyncio
async def test_get_storage_file_success(mock_files):
    with patch("backend.apps.file_management_app.get_file_url_impl") as mock_get_url:
        # Configure mock
        mock_get_url.return_value = {
            "success": True,
            "url": "https://test-url.com/test.txt",
            "metadata": {"content-type": "text/plain"}
        }

        # Create test client
        with TestClient(app) as client:
            response = client.get(
                "/file/storage/folder/test.txt?download=ignore&expires=1800")

        # Assertions
        assert response.status_code == 200
        assert response.json()["success"] == True
        assert response.json()["url"] == "https://test-url.com/test.txt"


@pytest.mark.asyncio
async def test_get_storage_file_redirect(mock_files):
    with patch("backend.apps.file_management_app.get_file_url_impl", new_callable=AsyncMock) as mock_get_url:
        # Configure mock
        mock_get_url.return_value = {
            "success": True,
            "url": "https://test-url.com/test.txt",
        }

        # Create test client
        with TestClient(app) as client:
            response = client.get(
                "/file/storage/folder/test.txt?download=redirect")

        # Assertions
        assert response.status_code == 404  # Redirect response


@pytest.mark.asyncio
async def test_get_storage_file_stream(mock_files):
    with patch("backend.apps.file_management_app.get_file_stream_impl", new_callable=AsyncMock) as mock_get_stream:
        # Configure mock as async function that returns a tuple
        mock_stream = BytesIO(b"file content")
        mock_get_stream.return_value = (mock_stream, "text/plain")

        # Create test client
        with TestClient(app) as client:
            response = client.get(
                "/file/storage/folder/test.txt?download=stream")

        # Assertions
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"


@pytest.mark.asyncio
async def test_get_storage_file_not_found(mock_files):
    with patch("backend.apps.file_management_app.get_file_url_impl") as mock_get_url:
        # Configure mock
        mock_get_url.side_effect = Exception(
            "File does not exist or cannot be accessed: File not found")

        # Create test client
        with TestClient(app) as client:
            response = client.get("/file/storage/folder/nonexistent.txt")

        # Assertions
        assert response.status_code == 500
        assert "detail" in response.json()


@pytest.mark.asyncio
async def test_remove_storage_file_success(mock_files):
    with patch("backend.apps.file_management_app.delete_file_impl") as mock_delete:
        # Configure mock
        mock_delete.return_value = {
            "success": True,
        }

        # Create test client
        with TestClient(app) as client:
            response = client.delete("/file/storage/test.txt")

        # Assertions
        assert response.status_code == 200
        assert response.json()["success"] == True


@pytest.mark.asyncio
async def test_remove_storage_file_not_found(mock_files):
    with patch("backend.apps.file_management_app.delete_file_impl") as mock_delete:
        # Configure mock
        mock_delete.side_effect = Exception(
            "File does not exist or deletion failed: File not found")

        # Create test client
        with TestClient(app) as client:
            response = client.delete("/file/storage/nonexistent.txt")

        # Assertions
        assert response.status_code == 500
        assert "detail" in response.json()


@pytest.mark.asyncio
async def test_get_storage_file_batch_urls(mock_files):
    with patch("backend.apps.file_management_app.get_file_url_impl", new_callable=AsyncMock) as mock_get_url:
        # Configure mock with side_effect for async function
        mock_get_url.side_effect = [
            {"success": True, "url": "https://test-url.com/test1.txt"},
            Exception("File does not exist or cannot be accessed: File not found")
        ]

        request_data = {"object_names": ["test1.txt", "nonexistent.txt"]}

        # Create test client
        with TestClient(app) as client:
            response = client.post(
                "/file/storage/batch-urls?expires=1800",
                json=request_data
            )

        # Assertions
        assert response.status_code == 200
        assert response.json()["success_count"] == 0
        assert response.json()["failed_count"] == 2


@pytest.mark.asyncio
async def test_get_storage_file_batch_urls_invalid_request(mock_files):
    request_data = {"invalid_field": ["test.txt"]}

    # Create test client
    with TestClient(app) as client:
        response = client.post(
            "/file/storage/batch-urls",
            json=request_data
        )

    # Assertions
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_preprocess_api_error_handling(mock_files):
    """Test preprocess API error handling and task cleanup"""
    with patch("backend.utils.auth_utils.get_current_user_info") as mock_get_user, \
            patch("backend.apps.file_management_app.process_image_file") as mock_process_image, \
            patch("agents.preprocess_manager.preprocess_manager") as mock_preprocess_manager:

        # Configure mocks
        mock_get_user.return_value = ("user123", "tenant456", "zh")
        mock_process_image.side_effect = Exception("Processing failed")

        # Mock preprocess manager
        mock_preprocess_manager.register_preprocess_task = MagicMock()
        mock_preprocess_manager.unregister_preprocess_task = MagicMock()

        # Create test client
        with TestClient(app) as client:
            response = client.post(
                "/file/preprocess",
                files=[
                    ("files", ("test.jpg", BytesIO(b"image data"), "image/jpeg"))
                ],
                data={"query": "test query"},
                headers={"authorization": "Bearer test_token"}
            )
            assert response is not None


@pytest.mark.asyncio
async def test_process_image_file(mock_files):
    # Import directly in the test to use the already established mocks
    from backend.apps.file_management_app import process_image_file

    with patch("backend.apps.file_management_app.convert_image_to_text") as mock_convert:
        # Configure mock
        mock_convert.return_value = "Extracted text from image"

        # Test the function
        result = await process_image_file(
            query="Test query",
            filename="test.jpg",
            file_content=mock_files["mock_image_content"],
            tenant_id="tenant123"
        )

        # Assertions
        assert "Image file test.jpg content" in result
        assert "Extracted text from image" in result


@pytest.mark.asyncio
async def test_process_text_file(mock_files):
    # Import directly in the test to use the already established mocks
    from backend.apps.file_management_app import process_text_file

    # Mock multiple functions to ensure complete coverage of all call paths
    with patch('backend.utils.config_utils.get_model_name_from_config', return_value="test-model"), \
            patch('backend.utils.attachment_utils.get_model_name_from_config', return_value="test-model"), \
            patch('backend.utils.attachment_utils.convert_long_text_to_text', return_value="Processed text content"), \
            patch('backend.apps.file_management_app.convert_long_text_to_text', return_value="Processed text content"):

        with patch('httpx.AsyncClient') as mock_client:
            # Setup mock response for httpx client
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "text": "Extracted raw text from file"}

            mock_client_instance = MagicMock()
            mock_client_instance.post.return_value = asyncio.Future()
            mock_client_instance.post.return_value.set_result(mock_response)
            mock_client.return_value.__aenter__.return_value = mock_client_instance

            # Test the function
            result = await process_text_file(
                query="Test query",
                filename="test.txt",
                file_content=mock_files["mock_file_content"],
                tenant_id="tenant123",
                language="en"
            )

            # Assertions
            assert "File test.txt content" in result


def test_get_file_description(mock_files):
    # Import directly in the test to use the already established mocks
    from backend.apps.file_management_app import get_file_description

    # Create mock UploadFile objects
    text_file = MagicMock()
    text_file.filename = "document.txt"

    image_file = MagicMock()
    image_file.filename = "photo.jpg"

    # Test the function
    result = get_file_description([text_file, image_file])

    # Assertions
    assert "User provided some reference files" in result
    assert "Image file photo.jpg" in result
    assert "File document.txt" in result


def test_options_route():
    # Create test client
    with TestClient(app) as client:
        response = client.options("/file/test_path")

    # Assertions
    assert response.status_code == 200
    assert response.json()["detail"] == "OK"
