"""Optional real inference smoke test. Downloads the tiny model (~75 MB).

This checks decoding/inference, NOT Persian transcription accuracy.
Run explicitly with: python tests/engine_smoke.py
"""
import os
from pathlib import Path
import tempfile
import wave

os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
os.environ['HF_HUB_DISABLE_XET'] = '1'
from faster_whisper import WhisperModel

model = WhisperModel('tiny', device='cpu', compute_type='int8',
                     download_root=str(Path(__file__).resolve().parents[1] / 'models'))
with tempfile.TemporaryDirectory() as folder:
    audio = str(Path(folder) / 'silence.wav')
    with wave.open(audio, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\x00\x00' * 16000)
    segments, info = model.transcribe(audio, language='fa', vad_filter=False, beam_size=1)
    list(segments)
    assert info.language == 'fa'
    assert info.duration > 0
    print('Real CPU model loading, audio decoding and inference passed. No accuracy claim.')
