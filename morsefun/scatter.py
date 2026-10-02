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

A cloud does not hold still, though, so a single fixed spectrum is not enough.
:class:`EvolvingSpectrum` carries one component per scattering core, each free
to change its level, its mean Doppler and its width as the message goes out,
and :func:`evolving_channel` colours *one* stream of white noise through that
changing spectrum, frame by frame, with the overlap-add of a short-time Fourier
transform.  Because every frame filters the same white noise, nothing clicks or
jumps at a frame boundary: the note just goes on breathing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dsp import smooth_noise

GRID_POINTS = 8192

#: Grid points per smoothing width: enough to draw a smooth shape, no more.
POINTS_PER_WIDTH = 8

#: How many frequency bins the narrowest part of a spectrum should get.  A
#: narrow spectrum is given a long analysis block to resolve it -- which it can
#: afford, because a cell that narrow is also a cell that changes slowly.
BINS_PER_SPREAD = 10


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

    # Resolution follows the smoothing width: a handful of points per width is
    # all a smooth shape needs, and a narrow spectrum on a huge grid would cost
    # a kernel thousands of taps long for nothing.
    points = int(np.clip(POINTS_PER_WIDTH * (hi - lo) / width, 64, points))
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


def _shape_on(freqs: np.ndarray, playable: np.ndarray, grid: np.ndarray,
              psd: np.ndarray) -> np.ndarray | None:
    """Sample a power spectrum onto FFT bins, or ``None`` if nothing lands.

    A spectrum can be narrower than one bin -- a skywave trace is milliHertz
    wide and the bins are tenths of a Hz -- and interpolating it would then come
    back all zeros and synthesise silence.  In that case the whole of it goes in
    the nearest bin, which is the best a transform this length can say.
    """
    shape = np.where(playable, np.interp(freqs, grid, psd, left=0.0, right=0.0), 0.0)
    if shape.sum() > 0:
        return shape
    total = float(psd.sum())
    if total <= 0:
        return None
    centre = float(np.sum(grid * psd) / total)
    candidates = np.where(playable)[0]
    if candidates.size == 0:
        return None
    nearest = candidates[np.argmin(np.abs(freqs[candidates] - centre))]
    if abs(freqs[nearest] - centre) > max(abs(freqs[1] - freqs[0]), 1e-9):
        return None            # the spectrum is outside the band, not just narrow
    shape = np.zeros_like(freqs)
    shape[nearest] = total
    return shape


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
    playable = (freqs + tone_hz > 20.0) & (freqs + tone_hz < sample_rate / 2.0 - 20.0)
    shape = _shape_on(freqs, playable, grid, psd)
    if shape is None:
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


@dataclass
class Component:
    """One scattering core, as the channel sees it.

    ``freqs`` and ``weights`` are the core's own scatterers.  The three series
    are per frame of the synthesis: ``gain`` scales its power, ``shift`` moves
    its whole note in Hz, and ``width`` stretches its spread about its centre.
    """

    freqs: np.ndarray
    weights: np.ndarray
    centre_hz: float = 0.0
    gain: np.ndarray | None = None
    shift: np.ndarray | None = None
    width: np.ndarray | None = None

    def transform(self, frame: int) -> tuple[np.ndarray, np.ndarray]:
        """This core's Doppler samples and weights as they are in ``frame``."""
        width = 1.0 if self.width is None else float(self.width[min(frame, self.width.size - 1)])
        shift = 0.0 if self.shift is None else float(self.shift[min(frame, self.shift.size - 1)])
        gain = 1.0 if self.gain is None else float(self.gain[min(frame, self.gain.size - 1)])
        freqs = self.centre_hz + (self.freqs - self.centre_hz) * width + shift
        return freqs, self.weights * gain


class EvolvingSpectrum:
    """The Doppler spectrum of a whole cell, on a fixed grid, frame by frame.

    The grid is in Hz relative to the carrier and wide enough for every frame,
    so the components can wander about inside it without the shape being
    clipped.  Weights are *not* renormalised per frame: a core that fades is
    meant to come out quieter.
    """

    def __init__(self, components: list[Component], points: int = 2048,
                 smooth_hz: float | None = None):
        self.components = [c for c in components if c.freqs.size]
        self.frames = max((c.gain.size if c.gain is not None else 1)
                          for c in self.components) if self.components else 1
        lo, hi, spread = 0.0, 0.0, 1.0
        if self.components:
            freqs = np.concatenate([c.freqs for c in self.components])
            weights = np.concatenate([c.weights for c in self.components])
            mean = float(np.sum(freqs * weights) / max(float(weights.sum()), 1e-12))
            spread = float(np.sqrt(np.sum(weights * (freqs - mean) ** 2)
                                   / max(float(weights.sum()), 1e-12)))
            edges = []
            for c in self.components:
                stretch = 1.0 if c.width is None else float(np.max(c.width))
                low = 0.0 if c.shift is None else float(np.min(c.shift))
                high = 0.0 if c.shift is None else float(np.max(c.shift))
                centre, fmin, fmax = c.centre_hz, float(c.freqs.min()), float(c.freqs.max())
                edges.append(centre + (fmin - centre) * stretch + low)
                edges.append(centre + (fmax - centre) * stretch + high)
            lo, hi = min(edges), max(edges)
        # No absolute floor: a libration-minimum echo or a 2200 m skywave trace
        # is hundredths of a Hz wide, and a 1 Hz kernel would smear it into
        # something it is not.  Callers who are about to synthesise pass the
        # resolution they can actually reach.
        self.width_hz = float(smooth_hz) if smooth_hz else max(spread / 12.0, 1e-4)
        if hi - lo < 8 * self.width_hz:
            middle = 0.5 * (lo + hi)
            lo, hi = middle - 4 * self.width_hz, middle + 4 * self.width_hz
        lo, hi = lo - 4 * self.width_hz, hi + 4 * self.width_hz
        self.points = int(np.clip(POINTS_PER_WIDTH * (hi - lo) / self.width_hz,
                                  96, points))
        self.grid = np.linspace(lo, hi, self.points)
        self._range = (lo, hi)
        step = (hi - lo) / max(self.points - 1, 1)
        sigma = max(self.width_hz / step, 1.0)
        half = int(np.ceil(4 * sigma))
        kernel = np.exp(-0.5 * (np.arange(-half, half + 1) / sigma) ** 2)
        self._kernel = kernel / kernel.sum()
        self._mean: np.ndarray | None = None

    def psd(self, frame: int) -> np.ndarray:
        """The power spectrum in one frame, on :attr:`grid`."""
        total = np.zeros(self.points)
        for component in self.components:
            freqs, weights = component.transform(frame)
            hist, _ = np.histogram(freqs, bins=self.points, range=self._range, weights=weights)
            total += hist
        return np.convolve(total, self._kernel, mode="same")

    def mean_psd(self) -> np.ndarray:
        """The spectrum averaged over the whole message: what a report quotes."""
        if self._mean is None:
            total = np.zeros(self.points)
            for frame in range(self.frames):
                total += self.psd(frame)
            self._mean = total / max(self.frames, 1)
        return self._mean

    def moments(self) -> tuple[float, float]:
        """Mean Doppler and spread of the average spectrum, in Hz."""
        psd = self.mean_psd()
        total = float(psd.sum())
        if total <= 0:
            return 0.0, 0.0
        mean = float(np.sum(self.grid * psd) / total)
        spread = float(np.sqrt(np.sum(psd * (self.grid - mean) ** 2) / total))
        return mean, spread

    def retune(self, hz: float) -> None:
        """Tune the whole return by ``hz``, the way an operator would."""
        self.grid = self.grid + float(hz)
        self._range = (self._range[0] + float(hz), self._range[1] + float(hz))


def block_size(spread_hz: float, sample_rate: int, n: int,
               bins: int = BINS_PER_SPREAD, lo: int = 2048, hi: int = 65536) -> int:
    """Analysis block long enough to resolve ``spread_hz`` with ``bins`` bins."""
    want = bins * sample_rate / max(float(spread_hz), 1.0)
    want = float(np.clip(want, lo, hi))
    size = 1 << int(np.ceil(np.log2(want)))
    # Never longer than a quarter of the message: no transform can resolve
    # something narrower than one over its own length, so asking for a block
    # that spans the whole render buys nothing and leaves no frames to add.
    ceiling = 1 << int(np.floor(np.log2(max(int(n) // 4, lo))))
    return int(min(size, max(lo, ceiling)))


def frame_count(n: int, block: int) -> int:
    """How many analysis frames :func:`evolving_channel` will ask the cell for."""
    hop = max(int(block) // 2, 1)
    return int(max(1, (max(int(n), 1) + hop - 1) // hop + 1))


def evolving_channel(
    n: int, sample_rate: int, spectrum: EvolvingSpectrum, tone_hz: float,
    rng: np.random.Generator, block: int = 8192,
) -> np.ndarray:
    """A complex Gaussian scatter process whose spectrum changes as it goes.

    One white noise sequence is coloured frame by frame -- Hann window in,
    overlap-add out, divided by the window power so the seams are exact -- so
    the result is a single coherent process that happens to be fading, wandering
    and breathing the way the cell does.  Normalised to unit mean power, with
    anything outside the audio band dropped rather than folded back.
    """
    if n <= 0 or not spectrum.components:
        return np.zeros(max(n, 0), dtype=np.complex128)
    block = max(int(block), 256)
    hop = block // 2
    frames = frame_count(n, block)
    total = (frames - 1) * hop + block
    window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(block) / block)

    white = rng.standard_normal(total) + 1j * rng.standard_normal(total)
    out = np.zeros(total, dtype=np.complex128)
    norm = np.zeros(total)
    freqs = np.fft.fftfreq(block, 1.0 / sample_rate)
    playable = (freqs + tone_hz > 20.0) & (freqs + tone_hz < sample_rate / 2.0 - 20.0)

    for frame in range(frames):
        start = frame * hop
        norm[start:start + block] += window**2
        psd = spectrum.psd(min(frame, spectrum.frames - 1))
        shape = _shape_on(freqs, playable, spectrum.grid, psd)
        if shape is None:
            continue
        segment = white[start:start + block] * window
        coloured = np.fft.ifft(np.fft.fft(segment) * np.sqrt(shape))
        out[start:start + block] += coloured * window

    # Weighted overlap-add divides by the window power, but at the two ends only
    # one window covers each sample and that power goes to zero: dividing there
    # would amplify the edge into a crack louder than the signal.  Clamping it
    # tapers the first and last half block instead, which is silence anyway.
    steady = float(np.sum(window**2) / hop)
    out = out[:n] / np.maximum(norm[:n], 0.25 * steady)
    power = float(np.mean(np.abs(out) ** 2))
    if power <= 1e-30:
        return np.zeros(n, dtype=np.complex128)
    return out / np.sqrt(power)


@dataclass
class Carrier:
    """A path that arrives coherently: one tone, wandering slowly.

    Volume scatter is diffuse and belongs in :class:`EvolvingSpectrum`, but a
    skywave hop off a layer is not: it arrives as a carrier, and what the
    ionosphere does to it is move it about by milliHertz.  Two of them at
    slightly different Doppler beat against each other, which is the slow QSB
    on every low-band QRSS screen -- it comes out of the sum, not out of a
    fading model.
    """

    shift_hz: float = 0.0
    spread_hz: float = 0.0        # rms of its frequency wander
    wander_rate_hz: float = 0.01  # how fast it wanders
    level: float = 1.0            # amplitude, before normalising
    fade_db: float = 0.0          # slow fading of its own
    fade_rate_hz: float = 0.01


def coherent_channel(
    n: int, sample_rate: int, carriers: list[Carrier], rng: np.random.Generator,
    ticks_hz: float = 20.0,
) -> np.ndarray:
    """Sum of slowly wandering carriers, normalised to unit mean power.

    The wander is drawn at a few ticks a second and interpolated, because
    nothing here changes faster than that and a message in QRSS runs for
    minutes: there is no point building milliHertz noise at the sample rate.
    """
    if n <= 0 or not carriers:
        return np.zeros(max(n, 0), dtype=np.complex128)
    ticks = max(int(n / sample_rate * max(ticks_hz, 0.5)) + 2, 8)
    coarse = np.linspace(0.0, n / sample_rate, ticks)
    t = np.arange(n) / sample_rate
    out = np.zeros(n, dtype=np.complex128)
    for carrier in carriers:
        wander = np.clip(smooth_noise(ticks, ticks / max(coarse[-1], 1e-9),
                                      max(carrier.wander_rate_hz, 1e-4), rng), -3.0, 3.0)
        freq = carrier.shift_hz + carrier.spread_hz * np.interp(t, coarse, wander)
        amplitude = np.full(n, float(carrier.level))
        if carrier.fade_db > 0:
            swing = np.clip(smooth_noise(ticks, ticks / max(coarse[-1], 1e-9),
                                         max(carrier.fade_rate_hz, 1e-4), rng), -2.5, 2.5)
            fade = carrier.fade_db * (np.interp(t, coarse, swing) / 2.5 - 1.0) / 2.0
            amplitude = amplitude * np.power(10.0, fade / 20.0)
        phase = 2 * np.pi * np.cumsum(freq) / sample_rate + rng.uniform(0, 2 * np.pi)
        out += amplitude * np.exp(1j * phase)
    power = float(np.mean(np.abs(out) ** 2))
    if power <= 1e-30:
        return np.zeros(n, dtype=np.complex128)
    return out / np.sqrt(power)
