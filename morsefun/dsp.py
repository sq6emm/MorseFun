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
    "agc",
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
    """Tanh limiter: a waveshaper, kept only as a last-resort peak catcher.

    It bends the waveform, so it puts harmonics and splatter outside the IF
    filter, which no receiver does.  :func:`agc` is what the render uses.
    """
    return np.tanh(x / knee) * knee


def _decaying_max(x: np.ndarray, release_samples: float) -> np.ndarray:
    """``y[n] = max(x[n], r * y[n-1])``: a peak detector with an exponential release.

    Done a block at a time with a cumulative maximum in a scaled domain, so a
    QRSS render of a few million samples does not need a Python loop over them.
    """
    r = float(np.exp(-1.0 / max(release_samples, 1.0)))
    out = np.empty_like(x)
    state = 0.0
    block = 32768
    for start in range(0, x.size, block):
        seg = x[start:start + block]
        k = np.arange(seg.size, dtype=np.float64)
        grow = r ** (-k)                       # at most exp(block / release)
        y = (r ** k) * np.maximum.accumulate(seg * grow)
        y = np.maximum(y, state * r ** (k + 1.0))
        out[start:start + block] = y
        state = float(y[-1])
    return out


def _forward_max(x: np.ndarray, span: int) -> np.ndarray:
    """``max(x[n .. n+span])``: what is about to arrive, for a look-ahead."""
    out = x.copy()
    step = 1
    while step < span:
        shifted = np.empty_like(out)
        shifted[:-step] = out[step:]
        shifted[-step:] = out[-1]
        out = np.maximum(out, shifted)
        step *= 2
    return out


def agc(x: np.ndarray, sample_rate: int, knee: float = 0.72,
        attack_ms: float = 2.0, release_ms: float = 120.0) -> np.ndarray:
    """A receiver's AGC: gain that drops fast on a crash and recovers slowly.

    Below ``knee`` nothing happens.  A peak above it pulls the gain down over
    ``attack_ms`` (with that much look-ahead, so the first cycle of a crash does
    not get through) and the gain comes back over ``release_ms``, the fast
    setting a CW operator uses -- which is the familiar pumping, the noise floor
    sagging after each crash and climbing back within a dit or two.  Because it is a slowly varying *gain* and not a bend in the
    waveform, it creates nothing outside the filter the way a limiter does.
    """
    if x.size == 0:
        return x
    attack = max(int(attack_ms * sample_rate / 1000.0), 1)
    envelope = _decaying_max(np.abs(x), release_ms * sample_rate / 1000.0)
    envelope = _forward_max(envelope, attack)
    gain = knee / np.maximum(envelope, knee)
    # Ease the gain over the attack time instead of stepping it.
    taps = 2 * attack + 1
    padded = np.concatenate([np.full(attack, gain[0]), gain, np.full(attack, gain[-1])])
    cumulative = np.concatenate([[0.0], np.cumsum(padded)])
    gain = (cumulative[taps:] - cumulative[:-taps]) / taps
    return x * gain
