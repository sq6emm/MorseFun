"""What the signal bounces off on the way, and how fast it is moving.

Everything here is about one number: the Doppler frequency a scatterer puts on
the signal.  For a path that goes out and comes back the same way that is
``2 v_radial / lambda``; at 10 GHz the wavelength is 30 mm, so one metre per
second is 67 Hz -- which is why rain scatter on this band sounds like hissing
rather than like a tone, and why a mode that works on 2 m does not survive here
at all.

This module holds the primitives: the band, the ITU-R attenuation and
reflectivity curves, and the drop and flake populations that a scattering
volume is made of.  What a volume *looks like* to two stations -- its cores,
its shape, the angle they see it at -- is :mod:`morsefun.cell`.

Nothing here is a fixed curve.  Drops are sampled one at a time from a size
distribution and given their own fall speed, so no two renders see the same
rain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

C = 299_792_458.0

#: 12 mm/h of rain is the yardstick: at this rate the signal sits at whatever
#: signal-to-noise ratio was asked for, and other weather is louder or weaker.
REFERENCE_RATE_MM_H = 12.0

#: ITU-R P.838-3 specific attenuation coefficients, horizontal polarisation.
#: frequency GHz -> (k, alpha) for gamma = k * R**alpha  dB/km
_RAIN_ATTENUATION = (
    (1.0, 0.0000259, 0.9691),
    (2.0, 0.0000847, 1.0664),
    (4.0, 0.0006000, 1.2109),
    (6.0, 0.0017500, 1.3080),
    (8.0, 0.0041150, 1.3905),
    (10.0, 0.0121700, 1.2571),
    (12.0, 0.0238600, 1.1825),
    (15.0, 0.0448100, 1.1233),
    (20.0, 0.0916400, 1.0568),
    (25.0, 0.1571000, 0.9991),
    (30.0, 0.2403000, 0.9485),
)


@dataclass(frozen=True)
class Band:
    """An operating frequency, and the wavelength that follows from it."""

    hz: float

    @property
    def wavelength_m(self) -> float:
        return C / self.hz

    @property
    def ghz(self) -> float:
        return self.hz / 1e9

    @property
    def label(self) -> str:
        if self.hz >= 1e9:
            return f"{self.hz / 1e9:.6g} GHz"
        if self.hz >= 1e6:
            return f"{self.hz / 1e6:.6g} MHz"
        return f"{self.hz:.0f} Hz"

    def doppler_hz(self, velocity_mps: float | np.ndarray) -> float | np.ndarray:
        """Two-way Doppler shift for a radial velocity, in Hz."""
        return 2.0 * velocity_mps / self.wavelength_m

    def bistatic_doppler_hz(self, closing_mps: float | np.ndarray) -> float | np.ndarray:
        """Doppler for the *sum* of the closing speeds towards both ends.

        Scattering is bistatic: the transmitter and the receiver each see their
        own share of the motion, and only the sum is heard.  For a radar that
        transmits and receives in the same direction the sum is ``2 v`` and
        this is :meth:`doppler_hz` again.
        """
        return np.asarray(closing_mps, dtype=np.float64) / self.wavelength_m


def parse_band(text: str) -> Band:
    """``10G``, ``10GHz``, ``10.368 GHz``, ``1296``, ``144M``, ``3cm``, ``30mm``."""
    token = str(text).strip().lower().replace(" ", "")
    match = re.fullmatch(r"([0-9]*\.?[0-9]+)(ghz|g|mhz|m|khz|k|hz|cm|mm)?", token)
    if not match:
        raise ValueError(f"cannot read a frequency from {text!r}")
    value, unit = float(match.group(1)), match.group(2)
    if value <= 0:
        raise ValueError("frequency must be positive")
    if unit in ("cm", "mm"):
        metres = value / (100.0 if unit == "cm" else 1000.0)
        return Band(C / metres)
    scale = {"ghz": 1e9, "g": 1e9, "mhz": 1e6, "m": 1e6, "khz": 1e3,
             "k": 1e3, "hz": 1.0, None: 1e6}[unit]
    return Band(value * scale)


def rain_attenuation_db_km(rate_mm_h: float, band: Band) -> float:
    """Specific rain attenuation in dB/km (ITU-R P.838, log-interpolated)."""
    if rate_mm_h <= 0:
        return 0.0
    ghz = max(band.ghz, _RAIN_ATTENUATION[0][0])
    freqs = np.array([row[0] for row in _RAIN_ATTENUATION])
    ks = np.array([row[1] for row in _RAIN_ATTENUATION])
    alphas = np.array([row[2] for row in _RAIN_ATTENUATION])
    ghz = min(ghz, freqs[-1])
    k = float(np.exp(np.interp(np.log(ghz), np.log(freqs), np.log(ks))))
    alpha = float(np.interp(ghz, freqs, alphas))
    return k * rate_mm_h**alpha


def reflectivity_dbz(rate_mm_h: float) -> float:
    """Marshall-Palmer Z-R: Z = 200 R^1.6, in dBZ.

    Received power off a scattering volume follows its reflectivity, so the
    difference between two of these is the difference in signal strength:
    heavy rain is loud, dry snow is nearly nothing.
    """
    if rate_mm_h <= 0:
        return float("-inf")
    return float(10.0 * np.log10(200.0 * rate_mm_h**1.6))


def snow_relative_db(wet: bool) -> float:
    """What snow is worth against the same rate of rain.

    Dry snowflakes are poor scatterers -- the ice dielectric factor alone costs
    about 6.5 dB -- while wet ones in the melting layer, water-coated and
    still flake-sized, are brighter than the equivalent rain: the bright band.
    """
    return 3.0 if wet else -6.5


def drop_diameters(rate_mm_h: float, count: int, rng: np.random.Generator) -> np.ndarray:
    """Marshall-Palmer drop sizes in mm: ``N(D) = N0 exp(-4.1 R^-0.21 D)``."""
    rate = max(float(rate_mm_h), 0.01)
    lam = 4.1 * rate**-0.21                                  # 1/mm
    return np.clip(rng.exponential(1.0 / lam, size=int(count)), 0.1, 7.0)


def drop_fall_speed(diameters: np.ndarray) -> np.ndarray:
    """Atlas-Ulbrich terminal velocity: ``v = 9.65 - 10.3 exp(-0.6 D)`` m/s."""
    return np.clip(9.65 - 10.3 * np.exp(-0.6 * diameters), 0.2, 10.0)


def flake_diameters(rate_mm_h: float, count: int, rng: np.random.Generator) -> np.ndarray:
    """Gunn-Marshall aggregate sizes, as melted diameter in mm."""
    rate = max(float(rate_mm_h), 0.01)
    lam = 25.5 * rate**-0.48
    return np.clip(rng.exponential(1.0 / lam, size=int(count)), 0.1, 8.0)


def flake_fall_speed(diameters: np.ndarray, wet: bool = False) -> np.ndarray:
    """Aggregates fall at about a metre a second whatever their size."""
    return np.clip(0.8 * diameters**0.16 * (1.6 if wet else 1.0), 0.2, 3.0)


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """Median of ``values`` weighted by how hard each one scatters."""
    if values.size == 0:
        return 0.0
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    if cumulative[-1] <= 0:
        return float(np.median(values))
    return float(values[order][np.searchsorted(cumulative, 0.5 * cumulative[-1])])


def moments(freqs: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    """Mean Doppler and Doppler spread of a weighted population, in Hz."""
    if freqs.size == 0:
        return 0.0, 0.0
    total = float(np.sum(weights))
    if total <= 0:
        return 0.0, 0.0
    mean = float(np.sum(freqs * weights) / total)
    spread = float(np.sqrt(np.sum(weights * (freqs - mean) ** 2) / total))
    return mean, spread


@dataclass
class AuroraSpec:
    """Field-aligned E-region irregularities, drifting fast and coming in bursts.

    Honest about the band: the drift velocities here are hundreds of metres per
    second, so on 2 m the Doppler lands a few hundred Hz away and you hear the
    famous hoarse note, while at 10 GHz the same motion throws the signal tens
    of kHz off and nothing comes back inside the filter.  Set ``shift_hz`` and
    ``spread_hz`` to work in the audio domain instead of in physics.
    """

    drift_mps: float = 600.0         # bulk drift of the irregularities
    drift_spread_mps: float = 200.0  # turbulent spread
    toward: bool = False             # drifting towards you, so shifted up
    activity: float = 0.55           # fraction of the time it is alive
    burst_s: float = 4.0             # how long a surge lasts
    flutter_hz: float = 0.0          # extra amplitude flutter, Hz
    shift_hz: float | None = None    # override the physics, in audio Hz
    spread_hz: float | None = None
    cells: int = 4000


def aurora_doppler(spec: AuroraSpec, band: Band, rng: np.random.Generator):
    """Sample an auroral curtain: fast bulk drift with a turbulent spread."""
    sign = 1.0 if spec.toward else -1.0
    if spec.shift_hz is not None or spec.spread_hz is not None:
        shift = float(spec.shift_hz if spec.shift_hz is not None else 0.0)
        spread = float(spec.spread_hz if spec.spread_hz is not None else 150.0)
        freqs = rng.normal(shift, max(spread, 1.0), size=spec.cells)
        physical = False
    else:
        velocity = rng.normal(sign * spec.drift_mps, max(spec.drift_spread_mps, 1.0),
                              size=spec.cells)
        freqs = np.asarray(band.doppler_hz(velocity), dtype=np.float64)
        physical = True
    weights = rng.lognormal(0.0, 0.8, size=spec.cells)   # patchy reflectors
    weights /= weights.sum()

    mean, spread_hz = moments(freqs, weights)
    info = {
        "kind": "aurora",
        "from_physics": physical,
        "drift_mps": spec.drift_mps * sign if physical else None,
        "shift_hz": mean,
        "spread_hz": spread_hz,
        "activity": spec.activity,
        "burst_s": spec.burst_s,
        "scatterers": int(spec.cells),
        "attenuation_db": 0.0,
    }
    return freqs, weights, info
