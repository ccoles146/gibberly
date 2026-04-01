from typing import Iterator
import time
import numpy as np
import soundfile as sf


SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"


class FileAudioSource:
    """Streams a WAV file as 16kHz mono PCM chunks."""

    def __init__(self, path: str, chunk_ms: int = 100):
        self._path = path
        self._chunk_samples = int(SAMPLE_RATE * chunk_ms / 1000)

    def chunks(self) -> Iterator[bytes]:
        data, sr = sf.read(self._path, dtype=DTYPE, always_2d=False)
        # Convert stereo → mono
        if data.ndim == 2:
            data = data.mean(axis=1).astype(DTYPE)
        # Resample to 16kHz if needed
        if sr != SAMPLE_RATE:
            from scipy.signal import resample
            target_len = int(len(data) * SAMPLE_RATE / sr)
            data = resample(data, target_len).astype(DTYPE)

        # Sleep duration between chunks (in seconds)
        sleep_duration = self._chunk_samples / SAMPLE_RATE

        for i in range(0, len(data) - self._chunk_samples + 1, self._chunk_samples):
            yield data[i : i + self._chunk_samples].tobytes()
            time.sleep(sleep_duration)


class MicAudioSource:
    """Streams live microphone input as 16kHz mono PCM chunks."""

    def __init__(self, device: int = None, chunk_ms: int = 100):
        self._device = device
        self._chunk_samples = int(SAMPLE_RATE * chunk_ms / 1000)

    def chunks(self) -> Iterator[bytes]:
        """Yields chunks until KeyboardInterrupt."""
        import sounddevice as sd
        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=self._chunk_samples,
            device=self._device,
            channels=CHANNELS,
            dtype=DTYPE,
        ) as stream:
            while True:
                data, _ = stream.read(self._chunk_samples)
                yield bytes(data)


def list_devices() -> list:
    """Return available input audio devices."""
    import sounddevice as sd
    devices = sd.query_devices()
    return [
        {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
    ]
