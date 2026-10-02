"""Writing and reading 16-bit mono PCM WAV files."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np


def to_pcm16(samples: np.ndarray) -> bytes:
    """Floats in -1..1 to little-endian 16-bit PCM."""
    clipped = np.clip(samples, -1.0, 1.0)
    return np.where(clipped < 0, clipped * 32768.0, clipped * 32767.0).astype("<i2").tobytes()


def wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    """A complete 16-bit mono WAV file as bytes, for piping to a player."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(int(sample_rate))
        out.writeframes(to_pcm16(samples))
    return buffer.getvalue()


def write_wav(path: str | Path, samples: np.ndarray, sample_rate: int) -> Path:
    """Write ``samples`` (floats in -1..1) as a 16-bit mono WAV file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_bytes(samples, sample_rate))
    return path


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Read a 16-bit mono WAV file back as floats in -1..1."""
    with wave.open(str(path), "rb") as src:
        if src.getsampwidth() != 2:
            raise ValueError("only 16-bit files are supported")
        frames = src.readframes(src.getnframes())
        data = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
        if src.getnchannels() > 1:
            data = data.reshape(-1, src.getnchannels()).mean(axis=1)
        return data, src.getframerate()
