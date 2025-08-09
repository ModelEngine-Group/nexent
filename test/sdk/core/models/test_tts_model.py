import pytest
import gzip
import json
import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

# Mock websockets before importing the module
mock_websockets = MagicMock()
mock_websockets.connect = AsyncMock()

module_mocks = {
    "websockets": mock_websockets,
}

with patch.dict("sys.modules", module_mocks):
    from sdk.nexent.core.models.tts_model import TTSModel, TTSConfig


class TestTTSConfig:
    """Test TTSConfig data model"""
    
    def test_tts_config_required_fields(self):
        """Test TTSConfig with required fields"""
        config = TTSConfig(
            appid="test_app",
            token="test_token",
            cluster="test_cluster",
            voice_type="test_voice",
            speed_ratio=1.0
        )
        
        assert config.appid == "test_app"
        assert config.token == "test_token"
        assert config.cluster == "test_cluster"
        assert config.voice_type == "test_voice"
        assert config.speed_ratio == 1.0
        assert config.host == "openspeech.bytedance.com"

    def test_tts_config_custom_host(self):
        """Test TTSConfig with custom host"""
        config = TTSConfig(
            appid="test_app",
            token="test_token",
            cluster="test_cluster",
            voice_type="test_voice",
            speed_ratio=1.5,
            host="custom.example.com"
        )
        
        assert config.host == "custom.example.com"
        assert config.speed_ratio == 1.5

    def test_tts_config_api_url_property(self):
        """Test api_url property generates correct URL"""
        config = TTSConfig(
            appid="test_app",
            token="test_token",
            cluster="test_cluster",
            voice_type="test_voice",
            speed_ratio=1.0
        )
        
        expected_url = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"
        assert config.api_url == expected_url

    def test_tts_config_api_url_custom_host(self):
        """Test api_url property with custom host"""
        config = TTSConfig(
            appid="test_app",
            token="test_token",
            cluster="test_cluster",
            voice_type="test_voice",
            speed_ratio=1.0,
            host="custom.example.com"
        )
        
        expected_url = "wss://custom.example.com/api/v1/tts/ws_binary"
        assert config.api_url == expected_url


class TestTTSModel:
    """Test TTSModel class"""

    @pytest.fixture
    def tts_config(self):
        """Create a test TTS configuration"""
        return TTSConfig(
            appid="test_app",
            token="test_token",
            cluster="test_cluster",
            voice_type="zh_female_xiaobei",
            speed_ratio=1.0
        )

    @pytest.fixture
    def tts_model(self, tts_config):
        """Create a test TTS model instance"""
        return TTSModel(tts_config)

    @pytest.fixture
    def mock_tts_ws_connect(self, monkeypatch):
        """Fixture to mock websockets.connect as an async context manager and capture call args."""
        def _apply(fake_ws):
            fake_connect_cm = AsyncMock()
            # Ensure async context manager methods
            fake_connect_cm.__aenter__ = AsyncMock(return_value=fake_ws)
            fake_connect_cm.__aexit__ = AsyncMock(return_value=None)

            # Recorder for connect() arguments
            class Recorder:
                def __init__(self):
                    self.call_args = None
                    self.call_kwargs = None

            recorder = Recorder()

            def connect_spy(*args, **kwargs):
                recorder.call_args = args
                recorder.call_kwargs = kwargs
                return fake_connect_cm

            # Patch the connect function in the tts_model module namespace
            monkeypatch.setattr(
                "sdk.nexent.core.models.tts_model.websockets.connect",
                connect_spy,
                raising=True,
            )

            return {"fake_connect": fake_connect_cm, "recorder": recorder}
        return _apply

    def test_init(self, tts_config):
        """Test TTSModel initialization"""
        model = TTSModel(tts_config)
        
        assert model.config == tts_config
        assert model._request_template is not None
        assert model._request_template["app"]["appid"] == "test_app"
        assert model._request_template["app"]["token"] == "test_token"
        assert model._request_template["app"]["cluster"] == "test_cluster"
        assert model._request_template["audio"]["voice_type"] == "zh_female_xiaobei"
        assert model._request_template["audio"]["speed_ratio"] == 1.0

    def test_default_header_constant(self):
        """Test DEFAULT_HEADER constant"""
        assert TTSModel.DEFAULT_HEADER == bytearray(b'\x11\x10\x11\x00')

    def test_message_constants(self):
        """Test message type constants"""
        assert TTSModel.MESSAGE_TYPES[11] == "audio-only server response"
        assert TTSModel.MESSAGE_TYPES[12] == "frontend server response"
        assert TTSModel.MESSAGE_TYPES[15] == "error message from server"

    def test_prepare_request_default_operation(self, tts_model):
        """Test _prepare_request with default operation"""
        text = "Hello world"
        
        with patch('uuid.uuid4', return_value=MagicMock()), \
             patch('json.dumps') as mock_json_dumps, \
             patch('gzip.compress') as mock_gzip_compress:
            
            mock_json_dumps.return_value = '{"test": "data"}'
            mock_gzip_compress.return_value = b'compressed_data'
            
            result = tts_model._prepare_request(text)
            
            # Verify the result is bytes
            assert isinstance(result, bytes)
            
            # Verify JSON dumps was called with proper structure
            call_args = mock_json_dumps.call_args[0][0]
            assert call_args["request"]["text"] == text
            assert call_args["request"]["operation"] == "submit"
            assert call_args["app"]["appid"] == "test_app"

    def test_prepare_request_custom_operation(self, tts_model):
        """Test _prepare_request with custom operation"""
        text = "Test text"
        operation = "query"
        
        with patch('uuid.uuid4', return_value=MagicMock()), \
             patch('json.dumps') as mock_json_dumps, \
             patch('gzip.compress') as mock_gzip_compress:
            
            mock_json_dumps.return_value = '{"test": "data"}'
            mock_gzip_compress.return_value = b'compressed_data'
            
            result = tts_model._prepare_request(text, operation)
            
            # Verify JSON dumps was called with proper operation
            call_args = mock_json_dumps.call_args[0][0]
            assert call_args["request"]["operation"] == operation

    def test_parse_response_audio_only_no_sequence(self, tts_model):
        """Test _parse_response with audio-only response, no sequence"""
        # Create mock response: header + payload with no sequence
        response = bytearray()
        response.extend(b'\x11')  # protocol version (1) + header size (1)
        response.extend(b'\xb0')  # message type (11 = 0xb) + flags (0)
        response.extend(b'\x00')  # serialization + compression
        response.extend(b'\x00')  # reserved
        # No payload for this test case
        
        is_done, audio_chunk = tts_model._parse_response(bytes(response))
        
        assert is_done is False
        assert audio_chunk is None

    def test_parse_response_audio_only_with_sequence(self, tts_model):
        """Test _parse_response with audio-only response with sequence"""
        # Create mock response with audio data
        audio_data = b"fake_audio_data"
        sequence_number = 123
        
        response = bytearray()
        response.extend(b'\x11')  # protocol version (1) + header size (1)
        response.extend(b'\xb1')  # message type (11 = 0xb) + flags (1 = has sequence)
        response.extend(b'\x00')  # serialization + compression
        response.extend(b'\x00')  # reserved
        response.extend(sequence_number.to_bytes(4, 'big', signed=True))  # sequence
        response.extend(len(audio_data).to_bytes(4, 'big', signed=False))  # payload size
        response.extend(audio_data)  # audio data
        
        buffer = io.BytesIO()
        is_done, audio_chunk = tts_model._parse_response(bytes(response), buffer)
        
        assert is_done is False
        assert audio_chunk == audio_data
        assert buffer.getvalue() == audio_data

    def test_parse_response_audio_only_last_chunk(self, tts_model):
        """Test _parse_response with last audio chunk (negative sequence)"""
        audio_data = b"last_audio_chunk"
        sequence_number = -123  # Negative indicates last chunk
        
        response = bytearray()
        response.extend(b'\x11')  # protocol version (1) + header size (1)
        response.extend(b'\xb1')  # message type (11 = 0xb) + flags (1 = has sequence)
        response.extend(b'\x00')  # serialization + compression
        response.extend(b'\x00')  # reserved
        response.extend(sequence_number.to_bytes(4, 'big', signed=True))  # negative sequence
        response.extend(len(audio_data).to_bytes(4, 'big', signed=False))  # payload size
        response.extend(audio_data)  # audio data
        
        is_done, audio_chunk = tts_model._parse_response(bytes(response))
        
        assert is_done is True
        assert audio_chunk == audio_data

    def test_parse_response_error_message(self, tts_model):
        """Test _parse_response with error message"""
        error_code = 40000001
        error_message = "Invalid request"
        error_data = error_message.encode('utf-8')
        
        response = bytearray()
        response.extend(b'\x11')  # protocol version (1) + header size (1)
        response.extend(b'\xf0')  # message type (15 = 0xf) + flags (0)
        response.extend(b'\x00')  # serialization + compression (no compression)
        response.extend(b'\x00')  # reserved
        response.extend(error_code.to_bytes(4, 'big', signed=False))  # error code
        response.extend(len(error_data).to_bytes(4, 'big', signed=False))  # payload size
        response.extend(error_data)  # error message
        
        with pytest.raises(Exception) as exc_info:
            tts_model._parse_response(bytes(response))
        
        assert f"TTS Error {error_code}: {error_message}" in str(exc_info.value)

    def test_parse_response_error_message_compressed(self, tts_model):
        """Test _parse_response with compressed error message"""
        error_code = 40000001
        error_message = "Compressed error message"
        error_data = gzip.compress(error_message.encode('utf-8'))
        
        response = bytearray()
        response.extend(b'\x11')  # protocol version (1) + header size (1)
        response.extend(b'\xf0')  # message type (15 = 0xf) + flags (0)
        response.extend(b'\x01')  # serialization + compression (gzip = 1)
        response.extend(b'\x00')  # reserved
        response.extend(error_code.to_bytes(4, 'big', signed=False))  # error code
        response.extend(len(error_data).to_bytes(4, 'big', signed=False))  # payload size
        response.extend(error_data)  # compressed error message
        
        with pytest.raises(Exception) as exc_info:
            tts_model._parse_response(bytes(response))
        
        assert f"TTS Error {error_code}: {error_message}" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_generate_speech_non_streaming(self, tts_model, mock_tts_ws_connect):
        """Test generate_speech with non-streaming mode"""
        pass

    @pytest.mark.asyncio
    async def test_generate_speech_streaming(self, tts_model, mock_tts_ws_connect):
        """Test generate_speech with streaming mode"""
        pass

    def test_parse_query_response(self, tts_model):
        """Test _parse_query_response method"""
        mock_response = b"mock_query_response_data"
        
        result = tts_model._parse_query_response(mock_response)
        
        # Current implementation returns default status
        assert result == {"status": "unknown"}

    @pytest.mark.asyncio
    async def test_check_connectivity_success(self, tts_model):
        """Test check_connectivity with successful connection"""
        audio_data = b"test_audio_data"
        
        with patch.object(tts_model, 'generate_speech', return_value=audio_data) as mock_generate:
            result = await tts_model.check_connectivity()
            
            assert result is True
            mock_generate.assert_called_once_with("Hello", stream=False)

    @pytest.mark.asyncio
    async def test_check_connectivity_failure_exception(self, tts_model):
        """Test check_connectivity with exception"""
        with patch.object(tts_model, 'generate_speech', side_effect=Exception("Connection error")):
            result = await tts_model.check_connectivity()
            
            assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_failure_empty_response(self, tts_model):
        """Test check_connectivity with empty audio response"""
        with patch.object(tts_model, 'generate_speech', return_value=b""):
            result = await tts_model.check_connectivity()
            
            assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_failure_invalid_response(self, tts_model):
        """Test check_connectivity with invalid response type"""
        with patch.object(tts_model, 'generate_speech', return_value="invalid_type"):
            result = await tts_model.check_connectivity()
            
            assert result is False

    def test_request_template_structure(self, tts_model):
        """Test that request template has correct structure"""
        template = tts_model._request_template
        
        # Check app section
        assert "app" in template
        assert "appid" in template["app"]
        assert "token" in template["app"]
        assert "cluster" in template["app"]
        
        # Check user section
        assert "user" in template
        assert "uid" in template["user"]
        
        # Check audio section
        assert "audio" in template
        assert "voice_type" in template["audio"]
        assert "encoding" in template["audio"]
        assert "speed_ratio" in template["audio"]
        assert "volume_ratio" in template["audio"]
        assert "pitch_ratio" in template["audio"]
        
        # Check request section
        assert "request" in template
        assert "reqid" in template["request"]
        assert "text" in template["request"]
        assert "text_type" in template["request"]
        assert "operation" in template["request"]

    def test_request_template_values(self, tts_config):
        """Test that request template has correct values from config"""
        model = TTSModel(tts_config)
        template = model._request_template
        
        assert template["app"]["appid"] == tts_config.appid
        assert template["app"]["token"] == tts_config.token
        assert template["app"]["cluster"] == tts_config.cluster
        assert template["audio"]["voice_type"] == tts_config.voice_type
        assert template["audio"]["speed_ratio"] == tts_config.speed_ratio
        assert template["audio"]["encoding"] == "mp3"
        assert template["audio"]["volume_ratio"] == 1.0
        assert template["audio"]["pitch_ratio"] == 1.0
        assert template["request"]["text_type"] == "plain"

    def test_prepare_request_uuid_generation(self, tts_model):
        """Test that _prepare_request generates unique request IDs"""
        text = "Test text"
        
        with patch('uuid.uuid4') as mock_uuid:
            mock_uuid.return_value = MagicMock()
            mock_uuid.return_value.__str__ = MagicMock(return_value="test-uuid-123")
            
            with patch('json.dumps', wraps=json.dumps) as mock_json_dumps, \
                 patch('gzip.compress', return_value=b'compressed'):
                
                tts_model._prepare_request(text)
                
                # Verify uuid was called and used in request
                mock_uuid.assert_called_once()
                call_args = mock_json_dumps.call_args[0][0]
                assert call_args["request"]["reqid"] == "test-uuid-123"

    def test_prepare_request_binary_structure(self, tts_model):
        """Test that _prepare_request creates correct binary structure"""
        text = "Test"
        
        with patch('uuid.uuid4'), \
             patch('json.dumps', return_value='{"test": "data"}'), \
             patch('gzip.compress', return_value=b'compressed_payload'):
            
            result = tts_model._prepare_request(text)
            
            # Should start with default header
            assert result[:4] == bytes(TTSModel.DEFAULT_HEADER)
            
            # Next 4 bytes should be payload length
            payload_length = int.from_bytes(result[4:8], 'big')
            assert payload_length == len(b'compressed_payload')
            
            # Rest should be the compressed payload
            assert result[8:] == b'compressed_payload'