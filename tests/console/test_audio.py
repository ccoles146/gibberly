import numpy as np
import pytest


def test_file_source_yields_pcm_chunks(tmp_path):
    import soundfile as sf
    # Create a 0.5s test WAV at 16kHz mono
    samples = np.zeros(8000, dtype=np.int16)
    wav_path = tmp_path / "test.wav"
    sf.write(str(wav_path), samples, 16000, subtype="PCM_16")

    from console.audio import FileAudioSource
    source = FileAudioSource(str(wav_path), chunk_ms=100)
    chunks = list(source.chunks())

    # 0.5s at 100ms chunks = 5 chunks
    assert len(chunks) == 5
    # Each chunk: 100ms * 16000 samples/s * 2 bytes/sample = 3200 bytes
    assert all(len(c) == 3200 for c in chunks)


def test_file_source_resamples_to_16khz(tmp_path):
    import soundfile as sf
    # Create a 44.1kHz file — should be resampled to 16kHz
    samples = np.zeros(22050, dtype=np.int16)  # 0.5s at 44.1kHz
    wav_path = tmp_path / "hifi.wav"
    sf.write(str(wav_path), samples, 44100, subtype="PCM_16")

    from console.audio import FileAudioSource
    source = FileAudioSource(str(wav_path), chunk_ms=100)
    chunks = list(source.chunks())

    # After resampling to 16kHz: 0.5s = 8000 samples = 5 chunks of 3200 bytes
    assert len(chunks) == 5
