from math import gcd
from typing import Iterator
import numpy as np
import soundfile as sf


SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"


class FileAudioSource:
    """Streams a WAV file as 16kHz mono PCM chunks, reading block-by-block."""

    def __init__(self, path: str, chunk_ms: int = 100):
        self._path = path
        self._chunk_samples = int(SAMPLE_RATE * chunk_ms / 1000)
        self.sleep_s = chunk_ms / 1000  # caller should await asyncio.sleep(source.sleep_s)

    def chunks(self) -> Iterator[bytes]:
        from scipy.signal import resample_poly

        with sf.SoundFile(self._path) as f:
            sr = f.samplerate
            if sr != SAMPLE_RATE:
                g = gcd(sr, SAMPLE_RATE)
                up, down = SAMPLE_RATE // g, sr // g
                # Read enough input samples to produce roughly one output chunk
                in_block = max(1, int(self._chunk_samples * down / up))
            else:
                up = down = 1
                in_block = self._chunk_samples

            buf = np.zeros(0, dtype=DTYPE)

            for block in f.blocks(blocksize=in_block, dtype=DTYPE, always_2d=False):
                # Stereo → mono
                if block.ndim == 2:
                    block = block.mean(axis=1).astype(DTYPE)
                # Resample block to 16kHz
                if sr != SAMPLE_RATE:
                    block = resample_poly(block, up, down).astype(DTYPE)
                buf = np.concatenate([buf, block])
                while len(buf) >= self._chunk_samples:
                    yield buf[: self._chunk_samples].tobytes()
                    buf = buf[self._chunk_samples :]

            # Flush remaining samples (zero-padded to full chunk)
            if len(buf) > 0:
                padded = np.zeros(self._chunk_samples, dtype=DTYPE)
                padded[: len(buf)] = buf
                yield padded.tobytes()


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
