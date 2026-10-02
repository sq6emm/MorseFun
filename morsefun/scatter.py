"""The scatter channel: a tone goes in, a hiss comes out.

A signal scattered off a moving volume is not one signal but thousands, each
with its own Doppler frequency, adding up with random phases.  That sum is a
complex Gaussian process whose power spectrum *is* the Doppler spectrum of the
scatterers, so this module builds exactly that: sample the scatterers (see
:mod:`morsefun.propagation`), turn their weighted Doppler frequencies into a
spectral shape, colour complex white noise with it, and multiply the keying
envelope by the result.

Two things follow for free.  The envelope of the sum is Rayleigh distributed,
so the signal flutters the way scatter really does, and anything the Doppler
throws outside the audio band simply is not there any more -- which is the
whole story of why 10 GHz aurora is not a mode.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dsp import smooth_noise

GRID_POINTS = 8192


@dataclass
class ScatterSpec:
    """How the scattered path is mixed with the direct one."""

    mode: str = "none"              # none | rain | snow | aurora
    rician_db: float = -99.0        # direct-to-scattered power ratio, dB
    smooth_hz: float | None = None  # Doppler spectrum smoothing; default spread/12
    scintillation_db: float = 0.0   # slow extra fading on top of Rayleigh
    scintillation_rate: float = 0.3
    retune: bool = True             # tune the return back onto the chosen note

    @property
    def active(self) -> bool:
        return self.mode not in ("none", "", None)


def doppler_spectrum(
    samples: np.ndarray,
    weights: np.ndarray,
    smooth_hz: float | None = None,
    points: int = GRID_POINTS,
) -> tuple[np.ndarray, np.ndarray]:
    """Weighted Doppler samples to a smooth power spectrum on a coarse grid.

    The grid is in Hz relative to the carrier: 0 means no Doppler at all.
    """
    if samples.size == 0:
        return np.zeros(2), np.zeros(2)
    mean = float(np.sum(samples * weights))
    spread = float(np.sqrt(np.sum(weights * (samples - mean) ** 2)))
    width = smooth_hz if smooth_hz else max(spread / 12.0, 1.0)
    lo = float(samples.min()) - 4 * width
    hi = float(samples.max()) + 4 * width
    if hi - lo < 8 * width:
        lo, hi = mean - 8 * width, mean + 8 * width

    grid = np.linspace(lo, hi, points)
    step = grid[1] - grid[0]
    hist, _ = np.histogram(samples, bins=points, range=(lo, hi), weights=weights)

    # Smooth the histogram with a Gaussian of the sampling width.
    sigma = max(width / step, 1.0)
    half = int(np.ceil(4 * sigma))
    kernel = np.exp(-0.5 * (np.arange(-half, half + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    psd = np.convolve(hist, kernel, mode="same")
    total = psd.sum()
    if total > 0:
        psd = psd / total
    return grid, psd


def audible_fraction(
    grid: np.ndarray, psd: np.ndarray, tone_hz: float, bandwidth: float, sample_rate: int
) -> float:
    """Share of the scattered power that lands inside the receiver's filter."""
    if psd.sum() <= 0:
        return 0.0
    inside = (np.abs(grid) <= bandwidth / 2.0) & (grid + tone_hz > 0) & (
        grid + tone_hz < sample_rate / 2.0)
    return float(psd[inside].sum() / psd.sum())


def channel(
    n: int,
    sample_rate: int,
    grid: np.ndarray,
    psd: np.ndarray,
    tone_hz: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """A complex Gaussian scatter process with the given Doppler spectrum.

    Normalised to unit mean power when anything at all is audible; the parts of
    the spectrum that would land outside the audio band are dropped, not folded
    back, so nothing aliases into a sound that was never there.
    """
    if n == 0 or psd.sum() <= 0:
        return np.zeros(n, dtype=np.complex128)
    freqs = np.fft.fftfreq(n, 1.0 / sample_rate)
    shape = np.interp(freqs, grid, psd, left=0.0, right=0.0)
    playable = (freqs + tone_hz > 20.0) & (freqs + tone_hz < sample_rate / 2.0 - 20.0)
    shape = np.where(playable, shape, 0.0)
    if shape.sum() <= 0:
        return np.zeros(n, dtype=np.complex128)

    white = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    coloured = np.fft.ifft(np.fft.fft(white) * np.sqrt(shape))
    power = float(np.mean(np.abs(coloured) ** 2))
    if power <= 1e-30:
        return np.zeros(n, dtype=np.complex128)
    return coloured / np.sqrt(power)


def activity_gate(
    n: int, sample_rate: int, rng: np.random.Generator,
    activity: float, burst_s: float, floor: float = 0.04,
) -> np.ndarray:
    """Aurora comes and goes: a soft random gate open ``activity`` of the time."""
    if n == 0:
        return np.zeros(0)
    activity = float(np.clip(activity, 0.0, 1.0))
    if activity >= 1.0:
        return np.ones(n)
    wander = smooth_noise(n, sample_rate, 1.0 / max(burst_s, 0.1), rng)
    threshold = float(np.quantile(wander, 1.0 - activity))
    gate = 1.0 / (1.0 + np.exp(-(wander - threshold) * 5.0))
    return floor + (1.0 - floor) * gate


def scintillate(
    n: int, sample_rate: int, rng: np.random.Generator, depth_db: float, rate_hz: float
) -> np.ndarray:
    """Slow amplitude wander on top of the fast Rayleigh fading."""
    if n == 0 or depth_db <= 0:
        return np.ones(n)
    wander = np.clip(smooth_noise(n, sample_rate, rate_hz, rng), -2.5, 2.5) / 2.5
    return np.power(10.0, depth_db * (wander - 1.0) / 2.0 / 20.0)


def apply_channel(
    envelope: np.ndarray, tone_hz: float, sample_rate: int, process: np.ndarray
) -> np.ndarray:
    """Key the scatter process: real audio at ``tone_hz``, spread by the Doppler."""
    n = envelope.size
    if n == 0 or process.size != n:
        return np.zeros(n)
    t = np.arange(n) / sample_rate
    return np.real(envelope * process * np.exp(2j * np.pi * tone_hz * t))


def rician_weights(rician_db: float) -> tuple[float, float]:
    """Amplitude weights for the direct and scattered paths."""
    k = 10.0 ** (float(rician_db) / 10.0)
    return float(np.sqrt(k / (k + 1.0))), float(np.sqrt(1.0 / (k + 1.0)))
