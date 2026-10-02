"""Turn a Morse timeline into a keyed audio tone.

The tone is deliberately imperfect: the envelope has a finite rise and fall,
the frequency can drift, the amplitude can fade (QSB) and mains hum can ride
on it.  Everything random comes from the caller's Generator, so a given seed
always produces the same signal.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dsp import smooth_noise
from .morse import Element


@dataclass
class ToneSpec:
    """How a single station's tone sounds."""

    freq: float = 600.0
    rise_ms: float = 5.0
    level: float = 1.0
    drift_hz: float = 0.0       # peak frequency wander, Hz
    drift_rate: float = 0.08    # how fast it wanders, Hz
    qsb_db: float = 0.0         # peak fading depth, dB
    qsb_rate: float = 0.25      # fading rate, Hz
    hum_depth: float = 0.0      # mains hum on the carrier, 0..1
    hum_hz: float = 50.0


def keying_envelope(
    elements: list[Element],
    sample_rate: int,
    rise_ms: float,
    pad: float = 0.0,
    length: int | None = None,
    offset: float = 0.0,
) -> np.ndarray:
    """Build the 0..1 keying envelope for ``elements``.

    Each key-down stretch gets a raised-cosine rise and fall of ``rise_ms``
    (shortened for an element too brief to hold a full ramp), which is what
    keeps the keying free of clicks.
    """
    total = sum(e.seconds for e in elements)
    n = length if length is not None else int(np.ceil((total + 2 * pad) * sample_rate)) or 1
    env = np.zeros(n)
    rise = max(rise_ms, 0.0) / 1000.0
    t = pad + offset
    for element in elements:
        if element.on:
            start = int(round(t * sample_rate))
            count = max(1, int(round(element.seconds * sample_rate)))
            ramp = max(1, min(int(round(rise * sample_rate)), count // 2))
            shape = np.ones(count)
            edge = 0.5 - 0.5 * np.cos(np.pi * np.arange(ramp) / ramp)
            shape[:ramp] = edge
            shape[count - ramp :] = edge[::-1]
            lo = max(0, start)
            hi = min(n, start + count)
            if hi > lo:
                env[lo:hi] = np.maximum(env[lo:hi], shape[lo - start : hi - start])
        t += element.seconds
    return env


def keyed_tone(
    elements: list[Element],
    sample_rate: int,
    spec: ToneSpec,
    rng: np.random.Generator,
    pad: float = 0.0,
    length: int | None = None,
    offset: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Render one station.  Returns ``(audio, keying_envelope)``."""
    env = keying_envelope(elements, sample_rate, spec.rise_ms, pad, length, offset)
    n = env.size
    if n == 0:
        return np.zeros(0), env

    t = np.arange(n) / sample_rate
    if spec.drift_hz > 0:
        freq = spec.freq + spec.drift_hz * smooth_noise(n, sample_rate, spec.drift_rate, rng)
    else:
        freq = np.full(n, spec.freq, dtype=np.float64)
    phase = 2 * np.pi * np.cumsum(freq) / sample_rate
    tone = np.sin(phase)

    amp = np.full(n, spec.level, dtype=np.float64)
    if spec.qsb_db > 0:
        wander = smooth_noise(n, sample_rate, spec.qsb_rate, rng)
        wander = np.clip(wander, -2.5, 2.5) / 2.5             # bounded, -1 .. +1
        fade_db = spec.qsb_db * (wander - 1.0) / 2.0          # 0 .. -qsb_db
        amp *= np.power(10.0, fade_db / 20.0)
    if spec.hum_depth > 0:
        amp *= 1.0 + spec.hum_depth * np.sin(2 * np.pi * spec.hum_hz * t)

    return tone * env * amp, env
