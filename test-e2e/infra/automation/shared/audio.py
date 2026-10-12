"""Translate a declared WAV asset to the voice endpoint's PCM16 contract."""
from array import array
import io
import sys
import wave


def stt_transport_audio(path) -> bytes:
    """Honor the declared asset format; legacy stt_wav may point to raw PCM."""
    data = path.read_bytes()
    if path.suffix.lower() == '.wav':
        return stt_pcm16(data)
    if path.suffix.lower() != '.pcm':
        raise ValueError('STT asset must declare .wav or 16 kHz mono PCM16 .pcm format')
    if not data or len(data) % 2 or data.startswith(b'RIFF'):
        raise ValueError('Declared raw PCM asset is empty, truncated or contains a WAV header')
    return data


def stt_pcm16(wav_bytes: bytes, target_rate: int = 16000) -> bytes:
    """Decode mono PCM16 WAV and resample without changing the source asset."""
    if target_rate <= 0:
        raise ValueError('target sample rate must be positive')
    with wave.open(io.BytesIO(wav_bytes), 'rb') as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getcomptype() != 'NONE':
            raise ValueError('STT asset must be uncompressed mono PCM16 WAV')
        rate = audio.getframerate()
        samples = array('h')
        samples.frombytes(audio.readframes(audio.getnframes()))
    if sys.byteorder != 'little':
        samples.byteswap()
    if not samples:
        raise ValueError('STT WAV has no audio frames')
    if rate != target_rate:
        converted = array('h')
        for i in range(len(samples) * target_rate // rate):
            position = i * rate / target_rate
            left = int(position)
            right = min(left + 1, len(samples) - 1)
            converted.append(round(samples[left] + (samples[right] - samples[left]) * (position - left)))
        samples = converted
    if not samples:
        raise ValueError('STT asset is shorter than one target frame')
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()
