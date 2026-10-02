"""Small FFT-based signal helpers shared by the synthesis and noise stages.

Everything here works on mono float arrays and needs nothing but NumPy.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "fast_length",
    "rms",
    "db_to_amp",
    "amp_to_db",
    "band_response",
    "bandpass",
    "smooth_noise",
    "soft_limit",
]


def fast_length(n: int) -> int:
    """The smallest length at least ``n`` that the FFT is quick about.

    Lengths with a big prime factor cost several times more than neighbouring
    ones built from 2s, 3s and 5s, and a render is nothing but transforms over
    its whole length.  Rounding up buys that back for a few samples of silence.
    """
    target = max(int(n), 1)
    best = 1 << int(np.ceil(np.log2(target)))     # a power of two always works
    five = 1
    while five < best:
        three = five
        while three < best:
            candidate = three
            while candidate < target:
                candidate *= 2
            best = min(best, candidate)
            three *= 3
        five *= 5
    return int(best)


def rms(x: np.ndarray) -> float:
    """Root mean square of ``x`` (0.0 for an empty array)."""
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def db_to_amp(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def amp_to_db(amp: float) -> float:
    return float(20.0 * np.log10(max(amp, 1e-12)))


def band_response(freqs: np.ndarray, center: float, bandwidth: float, order: int = 8) -> np.ndarray:
    """Super-Gaussian bandpass magnitude: flat top, steep skirts.

    The response is -3 dB at ``center ± bandwidth/2``, which is how a CW
    filter is specified.  ``order`` sets how fast the skirts fall away;
    8 is close to a good crystal filter without any ringing of its own.
    """
    half = max(bandwidth / 2.0, 1.0)
    x = np.abs(freqs - center) / half
    with np.errstate(over="ignore"):
        return np.exp(-np.log(2.0) * np.power(x, order))


def bandpass(x: np.ndarray, sample_rate: int, center: float, bandwidth: float, order: int = 8) -> np.ndarray:
    """Run ``x`` through the receiver's IF filter."""
    n = x.size
    if n == 0:
        return x
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
    spectrum *= band_response(freqs, center, bandwidth, order)
    return np.fft.irfft(spectrum, n)


def smooth_noise(n: int, sample_rate: int, rate_hz: float, rng: np.random.Generator) -> np.ndarray:
    """Slowly wandering noise with unit standard deviation.

    Used for anything that drifts rather than oscillates: fading, frequency
    drift, a wobbling heterodyne.  ``rate_hz`` is the Gaussian corner of the
    low-pass, so 0.3 Hz wanders over a few seconds.
    """
    if n == 0:
        return np.zeros(0)
    white = rng.standard_normal(n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
    spectrum *= np.exp(-0.5 * np.square(freqs / max(rate_hz, 1e-6)))
    out = np.fft.irfft(spectrum, n)
    spread = out.std()
    return out / spread if spread > 1e-12 else out


def soft_limit(x: np.ndarray, knee: float = 0.72) -> np.ndarray:
    """Tanh limiter, the way a receiver's AGC rounds off static crashes.

    Signals below ``knee`` pass almost untouched; peaks above it compress
    instead of clipping square.
    """
    return np.tanh(x / knee) * knee
