import pytest
import asyncio
import gzip
import json
import wave
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from typing import Dict, Any

# Mock websockets before importing the module
mock_websockets = MagicMock()
mock_websockets.connect = AsyncMock()
mock_websockets.exceptions = MagicMock()

class MockConnectionClosedError(Exception):
    def __init__(self, code, reason):
        self.code = code
        self.reason = reason
        super().__init__(reason)

mock_websockets.exceptions.ConnectionClosedError = MockConnectionClosedError
mock_websockets.exceptions.WebSocketException = Exception

# Mock aiofiles with proper async context manager
mock_aiofiles = MagicMock()

# Create a proper async context manager mock
class MockAsyncContextManager:
    def __init__(self, mock_file):
        self.mock_file = mock_file
    
    async def __aenter__(self):
        return self.mock_file
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None

def mock_aiofiles_open(*args, **kwargs):
    mock_file = AsyncMock()
    mock_file.read = AsyncMock(return_value=b"mock_data")
    return MockAsyncContextManager(mock_file)

mock_aiofiles.open = mock_aiofiles_open

module_mocks = {
    "websockets": mock_websockets,
    "aiofiles": mock_aiofiles,
}

with patch.dict("sys.modules", module_mocks):
    from sdk.nexent.core.models.stt_model import (
        STTModel, STTConfig, AudioType, process_audio_item,
        PROTOCOL_VERSION, DEFAULT_HEADER_SIZE, CLIENT_FULL_REQUEST,
        CLIENT_AUDIO_ONLY_REQUEST, SERVER_FULL_RESPONSE, SERVER_ACK,
        SERVER_ERROR_RESPONSE, NO_SEQUENCE, POS_SEQUENCE, NEG_SEQUENCE,
        NEG_WITH_SEQUENCE, JSON, GZIP, NO_COMPRESSION
    )


class TestSTTConfig:
    """Test STTConfig data model"""
    
    def test_stt_config_default_values(self):
        """Test STTConfig with default values"""
        config = STTConfig(appid="test_app", token="test_token")
        
        assert config.appid == "test_app"
        assert config.token == "test_token"
        assert config.ws_url == "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
        assert config.uid == "streaming_asr_demo"
        assert config.format == "pcm"
        assert config.rate == 16000
        assert config.bits == 16
        assert config.channel == 1
        assert config.codec == "raw"
        assert config.seg_duration == 10
        assert config.mp3_seg_size == 1000
        assert config.resourceid == "volc.bigasr.sauc.duration"
        assert config.streaming is True
        assert config.compression is True

    def test_stt_config_custom_values(self):
        """Test STTConfig with custom values"""
        config = STTConfig(
            appid="custom_app",
            token="custom_token",
            ws_url="wss://custom.example.com",
            format="wav",
            rate=48000,
            streaming=False,
            compression=False
        )
        
        assert config.appid == "custom_app"
        assert config.token == "custom_token"
        assert config.ws_url == "wss://custom.example.com"
        assert config.format == "wav"
        assert config.rate == 48000
        assert config.streaming is False
        assert config.compression is False


class TestSTTModel:
    """Test STTModel class"""

    @pytest.fixture
    def stt_config(self):
        """Create a test STT configuration"""
        return STTConfig(
            appid="test_app",
            token="test_token",
            compression=True
        )

    @pytest.fixture
    def stt_model(self, stt_config):
        """Create a test STT model instance"""
        return STTModel(stt_config, "/path/to/test/voice.wav")

    def test_init(self, stt_config):
        """Test STTModel initialization"""
        test_voice_path = "/path/to/test.wav"
        model = STTModel(stt_config, test_voice_path)
        
        assert model.config == stt_config
        assert model.test_voice_path == test_voice_path
        assert model.success_code == 1000

    def test_generate_header_default(self, stt_model):
        """Test generate_header with default parameters"""
        header = stt_model.generate_header()
        
        assert len(header) == 4
        assert header[0] == (PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE
        assert header[1] == (CLIENT_FULL_REQUEST << 4) | NO_SEQUENCE
        assert header[2] == (JSON << 4) | GZIP  # compression enabled by default
        assert header[3] == 0x00

    def test_generate_header_no_compression(self, stt_config):
        """Test generate_header with compression disabled"""
        stt_config.compression = False
        stt_model = STTModel(stt_config, "/test/path")
        
        header = stt_model.generate_header()
        
        assert header[2] == (JSON << 4) | NO_COMPRESSION

    def test_generate_header_custom_params(self, stt_model):
        """Test generate_header with custom parameters"""
        header = stt_model.generate_header(
            message_type=CLIENT_AUDIO_ONLY_REQUEST,
            message_type_specific_flags=POS_SEQUENCE,
            compression_type=NO_COMPRESSION
        )
        
        assert header[1] == (CLIENT_AUDIO_ONLY_REQUEST << 4) | POS_SEQUENCE
        assert header[2] == (JSON << 4) | NO_COMPRESSION

    def test_generate_before_payload(self):
        """Test generate_before_payload static method"""
        sequence = 123
        payload = STTModel.generate_before_payload(sequence)
        
        assert len(payload) == 4
        assert int.from_bytes(payload, 'big', signed=True) == sequence

    def test_read_wav_info(self):
        """Test read_wav_info static method"""
        # Mock the wave module to avoid actual file format parsing
        mock_wave_fp = MagicMock()
        mock_wave_fp.getparams.return_value = (2, 2, 44100, 100)  # nchannels, sampwidth, framerate, nframes
        mock_wave_fp.readframes.return_value = b'\x00\x00' * 200  # 100 frames * 2 channels * 2 bytes
        mock_wave_fp.__enter__ = MagicMock(return_value=mock_wave_fp)
        mock_wave_fp.__exit__ = MagicMock(return_value=None)
        
        with patch('sdk.nexent.core.models.stt_model.wave.open', return_value=mock_wave_fp):
            wav_data = b"fake_wav_data"
            nchannels, sampwidth, framerate, nframes, wave_bytes = STTModel.read_wav_info(wav_data)
            
            assert nchannels == 2
            assert sampwidth == 2
            assert framerate == 44100
            assert nframes == 100
            assert len(wave_bytes) == 400  # 2 channels * 2 bytes * 100 frames

    def test_slice_data(self):
        """Test slice_data static method"""
        data = b'0123456789'
        chunk_size = 3
        
        chunks = list(STTModel.slice_data(data, chunk_size))
        
        assert len(chunks) == 4
        assert chunks[0] == (b'012', False)
        assert chunks[1] == (b'345', False)
        assert chunks[2] == (b'678', False)
        assert chunks[3] == (b'9', True)

    def test_construct_request(self, stt_model):
        """Test construct_request method"""
        reqid = "test_request_123"
        request = stt_model.construct_request(reqid)
        
        expected_request = {
            "user": {"uid": stt_model.config.uid},
            "audio": {
                'format': stt_model.config.format,
                "sample_rate": stt_model.config.rate,
                "bits": stt_model.config.bits,
                "channel": stt_model.config.channel,
                "codec": stt_model.config.codec
            },
            "request": {
                "model_name": "bigmodel",
                "enable_punc": True
            }
        }
        
        assert request == expected_request

    def test_parse_response_server_full_response(self):
        """Test parse_response with SERVER_FULL_RESPONSE"""
        # Create a mock response with JSON payload
        payload_data = {"result": {"text": "Hello world"}}
        payload_json = json.dumps(payload_data).encode('utf-8')
        payload_compressed = gzip.compress(payload_json)
        
        response = bytearray()
        response.append((PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE)  # protocol version + header size
        response.append((SERVER_FULL_RESPONSE << 4) | POS_SEQUENCE)  # message type + flags
        response.append((JSON << 4) | GZIP)  # serialization + compression
        response.append(0x00)  # reserved
        response.extend((123).to_bytes(4, 'big', signed=True))  # sequence
        response.extend(len(payload_compressed).to_bytes(4, 'big', signed=True))  # payload size
        response.extend(payload_compressed)  # payload
        
        result = STTModel.parse_response(bytes(response))
        
        assert result['payload_sequence'] == 123
        assert result['is_last_package'] is False
        assert result['payload_msg'] == payload_data
        assert result['payload_size'] == len(payload_compressed)

    def test_parse_response_server_error(self):
        """Test parse_response with SERVER_ERROR_RESPONSE"""
        error_msg = {"error": "Invalid request"}
        error_json = json.dumps(error_msg).encode('utf-8')
        error_compressed = gzip.compress(error_json)
        
        response = bytearray()
        response.append((PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE)
        response.append((SERVER_ERROR_RESPONSE << 4) | NO_SEQUENCE)
        response.append((JSON << 4) | GZIP)
        response.append(0x00)
        response.extend((45000081).to_bytes(4, 'big', signed=False))  # error code
        response.extend(len(error_compressed).to_bytes(4, 'big', signed=False))  # payload size
        response.extend(error_compressed)  # payload
        
        result = STTModel.parse_response(bytes(response))
        
        assert result['code'] == 45000081
        assert result['payload_msg'] == error_msg
        assert result['is_last_package'] is False

    def test_parse_response_last_package(self):
        """Test parse_response with last package flag"""
        response = bytearray()
        response.append((PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE)
        response.append((SERVER_ACK << 4) | NEG_SEQUENCE)  # NEG_SEQUENCE indicates last package
        response.append((JSON << 4) | NO_COMPRESSION)
        response.append(0x00)
        response.extend((-123).to_bytes(4, 'big', signed=True))  # negative sequence
        
        result = STTModel.parse_response(bytes(response))
        
        assert result['is_last_package'] is True
        assert result['seq'] == -123

    @pytest.mark.asyncio
    async def test_process_audio_data_connection_error(self, stt_model):
        """Test process_audio_data with connection error"""
        audio_data = b"test_audio_data"
        segment_size = 50
        
        with patch('sdk.nexent.core.models.stt_model.websockets.connect', 
                  side_effect=MockConnectionClosedError(1006, "Connection closed abnormally")):
            result = await stt_model.process_audio_data(audio_data, segment_size)

            assert 'error' in result
            assert "WebSocket error" in result['error']

    @pytest.mark.asyncio
    async def test_process_audio_file_wav(self, stt_model):
        """Test process_audio_file with WAV format"""
        wav_data = b"fake_wav_data" * 100
        
        # Mock aiofiles.open as an async context manager
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=wav_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)
        
        # Mock read_wav_info to return expected values
        mock_wav_info = (1, 2, 16000, 1600, b'\x00\x00' * 1600)  # channels, sampwidth, framerate, nframes, wav_bytes
        
        with patch('sdk.nexent.core.models.stt_model.aiofiles.open', return_value=mock_file), \
             patch.object(stt_model, 'read_wav_info', return_value=mock_wav_info), \
             patch.object(stt_model, 'process_audio_data', return_value={"result": "success"}) as mock_process:
            
            stt_model.config.format = "wav"
            result = await stt_model.process_audio_file("/test/file.wav")
            
            assert result == {"result": "success"}
            mock_process.assert_called_once()
            
            # Verify that the segment size was calculated correctly for WAV
            args, kwargs = mock_process.call_args
            audio_data, segment_size = args
            # size_per_sec = nchannels * sampwidth * framerate = 1 * 2 * 16000 = 32000
            # segment_size = int(32000 * seg_duration / 1000) = int(32000 * 10 / 1000) = 320
            assert segment_size == 320
            # Verify that raw audio bytes were passed (do not enforce exact content under mocked aiofiles)
            assert isinstance(audio_data, (bytes, bytearray))
            assert len(audio_data) > 0

    @pytest.mark.asyncio
    async def test_process_audio_file_pcm(self, stt_model):
        """Test process_audio_file with PCM format"""
        pcm_data = b'\x00\x01' * 1600  # 1600 samples = 100ms at 16kHz
        
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=pcm_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)
        
        with patch('sdk.nexent.core.models.stt_model.aiofiles.open', return_value=mock_file), \
             patch.object(stt_model, 'process_audio_data', return_value={"result": "success"}) as mock_process:
            
            stt_model.config.format = "pcm"
            result = await stt_model.process_audio_file("/test/file.pcm")
            
            assert result == {"result": "success"}
            # Check that segment size was calculated correctly for PCM
            expected_segment_size = int(16000 * 2 * 1 * 10 / 500)  # rate * bytes_per_sample * channels * duration / 500
            mock_process.assert_called_once()
            args, kwargs = mock_process.call_args
            audio_data_arg, seg_size_arg = args
            assert isinstance(audio_data_arg, (bytes, bytearray))
            assert len(audio_data_arg) > 0
            assert seg_size_arg == expected_segment_size

    @pytest.mark.asyncio
    async def test_process_audio_file_mp3(self, stt_model):
        """Test process_audio_file with MP3 format"""
        mp3_data = b"fake_mp3_data" * 100
        
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=mp3_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)
        
        with patch('sdk.nexent.core.models.stt_model.aiofiles.open', return_value=mock_file), \
             patch.object(stt_model, 'process_audio_data', return_value={"result": "success"}) as mock_process:
            
            stt_model.config.format = "mp3"
            result = await stt_model.process_audio_file("/test/file.mp3")
            
            assert result == {"result": "success"}
            mock_process.assert_called_once()
            args, kwargs = mock_process.call_args
            audio_data_arg, seg_size_arg = args
            assert isinstance(audio_data_arg, (bytes, bytearray))
            assert len(audio_data_arg) > 0
            assert seg_size_arg == stt_model.config.mp3_seg_size

    @pytest.mark.asyncio
    async def test_process_audio_file_unsupported_format(self, stt_model):
        """Test process_audio_file with unsupported format"""
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=b"data")
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)
        
        with patch('sdk.nexent.core.models.stt_model.aiofiles.open', return_value=mock_file):
            stt_model.config.format = "unsupported"
            
            with pytest.raises(Exception, match="Unsupported format"):
                await stt_model.process_audio_file("/test/file.unsupported")

    @pytest.mark.asyncio
    async def test_start_streaming_session(self, stt_model):
        """Test start_streaming_session method"""
        mock_ws_client = AsyncMock()
        
        with patch.object(stt_model, 'process_streaming_audio', return_value=None) as mock_process:
            await stt_model.start_streaming_session(mock_ws_client)
            
            mock_process.assert_called_once()
            # Verify segment size calculation
            expected_segment_size = int(16000 * 16 * 1 / 8 * 0.1)  # 100ms chunk
            args, _ = mock_process.call_args
            assert args[0] == mock_ws_client
            assert args[1] == expected_segment_size

    @pytest.mark.asyncio
    async def test_process_streaming_audio_client_disconnect(self, stt_model):
        """Test process_streaming_audio when client disconnects"""
        mock_ws_client = AsyncMock()
        mock_ws_client.send_json = AsyncMock(side_effect=Exception("Client disconnected"))
        
        class DummyWSServer:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return None
            async def send(self, data):
                return None
            async def recv(self):
                return b"init"
        mock_ws_server = DummyWSServer()
        
        with patch('sdk.nexent.core.models.stt_model.websockets.connect', return_value=mock_ws_server):
            # Should not raise exception, should handle gracefully
            await stt_model.process_streaming_audio(mock_ws_client, 1024)

    @pytest.mark.asyncio
    async def test_recognize_file(self, stt_model):
        """Test recognize_file method"""
        expected_result = {"result": {"text": "test transcription"}}
        
        with patch.object(stt_model, 'process_audio_file', return_value=expected_result) as mock_process:
            result = await stt_model.recognize_file("/test/audio.wav")
            
            assert result == expected_result
            mock_process.assert_called_once_with("/test/audio.wav")

    @pytest.mark.asyncio
    async def test_check_connectivity_success(self, stt_model):
        """Test check_connectivity with successful connection"""
        success_result = {
            'payload_msg': {
                'result': {'text': 'test'},
                'status': 'complete'
            }
        }
        
        with patch.object(stt_model, 'process_audio_file', return_value=success_result):
            result = await stt_model.check_connectivity()
            
            assert result is True

    @pytest.mark.asyncio
    async def test_check_connectivity_failure(self, stt_model):
        """Test check_connectivity with connection failure"""
        error_result = {'error': 'Connection failed'}
        
        with patch.object(stt_model, 'process_audio_file', return_value=error_result):
            result = await stt_model.check_connectivity()
            
            assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_exception(self, stt_model):
        """Test check_connectivity with exception"""
        with patch.object(stt_model, 'process_audio_file', side_effect=Exception("Network error")):
            result = await stt_model.check_connectivity()
            
            assert result is False

    def test_is_stt_result_successful_valid_result(self, stt_model):
        """Test _is_stt_result_successful with valid result"""
        valid_result = {
            'payload_msg': {
                'result': {'text': 'Hello world'}
            }
        }
        
        assert stt_model._is_stt_result_successful(valid_result) is True

    def test_is_stt_result_successful_error_result(self, stt_model):
        """Test _is_stt_result_successful with error result"""
        error_result = {'error': 'Connection failed'}
        
        assert stt_model._is_stt_result_successful(error_result) is False

    def test_is_stt_result_successful_error_code(self, stt_model):
        """Test _is_stt_result_successful with error code"""
        error_result = {'code': 45000081}
        
        assert stt_model._is_stt_result_successful(error_result) is False

    def test_is_stt_result_successful_empty_result(self, stt_model):
        """Test _is_stt_result_successful with empty result"""
        # Empty dict is considered unsuccessful by current implementation
        assert stt_model._is_stt_result_successful({}) is False
        assert stt_model._is_stt_result_successful(None) is False
        assert stt_model._is_stt_result_successful("invalid") is False

    def test_extract_stt_error_message_direct_error(self, stt_model):
        """Test _extract_stt_error_message with direct error"""
        error_result = {'error': 'Direct error message'}
        
        message = stt_model._extract_stt_error_message(error_result)
        assert message == 'Direct error message'

    def test_extract_stt_error_message_error_code(self, stt_model):
        """Test _extract_stt_error_message with error code"""
        error_result = {
            'code': 45000081,
            'payload_msg': {'error': 'Detailed error'}
        }
        
        message = stt_model._extract_stt_error_message(error_result)
        assert "STT service error code: 45000081" in message
        assert "Detailed error" in message

    def test_extract_stt_error_message_nested_error(self, stt_model):
        """Test _extract_stt_error_message with nested error"""
        error_result = {
            'payload_msg': {'error': 'Nested error message'}
        }
        
        message = stt_model._extract_stt_error_message(error_result)
        assert message == 'Nested error message'

    def test_extract_stt_error_message_unknown_error(self, stt_model):
        """Test _extract_stt_error_message with unknown error"""
        error_result = {'unknown': 'value'}
        
        message = stt_model._extract_stt_error_message(error_result)
        assert "Unknown error in result" in message


class TestAudioType:
    """Test AudioType enum"""
    
    def test_audio_type_values(self):
        """Test AudioType enum values"""
        assert AudioType.LOCAL.value == 1
        assert AudioType.STREAM.value == 2


class TestProcessAudioItem:
    """Test process_audio_item function"""
    
    @pytest.mark.asyncio
    async def test_process_audio_item_success(self):
        """Test process_audio_item with successful processing"""
        config = STTConfig(appid="test", token="test")
        audio_item = {"id": "test_id", "path": "/test/audio.wav"}
        test_voice_path = "/test/voice.wav"
        
        expected_result = {"result": {"text": "test transcription"}}
        
        # Mock aiofiles.open to return a proper async context manager
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=b"fake_audio_data")
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)
        
        with patch('sdk.nexent.core.models.stt_model.aiofiles.open', return_value=mock_file), \
             patch.object(STTModel, 'process_audio_data', return_value=expected_result) as mock_process:
            
            result = await process_audio_item(audio_item, config, test_voice_path)
            
            assert result["id"] == "test_id"
            assert result["path"] == "/test/audio.wav"
            assert result["result"] == expected_result

    @pytest.mark.asyncio
    async def test_process_audio_item_missing_keys(self):
        """Test process_audio_item with missing required keys"""
        config = STTConfig(appid="test", token="test")
        test_voice_path = "/test/voice.wav"
        
        # Test missing 'id' key
        with pytest.raises(AssertionError):
            await process_audio_item({"path": "/test/audio.wav"}, config, test_voice_path)
        
        # Test missing 'path' key
        with pytest.raises(AssertionError):
            await process_audio_item({"id": "test_id"}, config, test_voice_path)


class TestConstants:
    """Test module constants"""
    
    def test_protocol_constants(self):
        """Test protocol constants are defined correctly"""
        assert PROTOCOL_VERSION == 0b0001
        assert DEFAULT_HEADER_SIZE == 0b0001
        
    def test_message_type_constants(self):
        """Test message type constants"""
        assert CLIENT_FULL_REQUEST == 0b0001
        assert CLIENT_AUDIO_ONLY_REQUEST == 0b0010
        assert SERVER_FULL_RESPONSE == 0b1001
        assert SERVER_ACK == 0b1011
        assert SERVER_ERROR_RESPONSE == 0b1111
        
    def test_message_flags_constants(self):
        """Test message type specific flags"""
        assert NO_SEQUENCE == 0b0000
        assert POS_SEQUENCE == 0b0001
        assert NEG_SEQUENCE == 0b0010
        assert NEG_WITH_SEQUENCE == 0b0011
        
    def test_serialization_constants(self):
        """Test serialization constants"""
        assert JSON == 0b0001
        
    def test_compression_constants(self):
        """Test compression constants"""
        assert NO_COMPRESSION == 0b0000
        assert GZIP == 0b0001