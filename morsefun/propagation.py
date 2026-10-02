"""What the signal bounces off on the way, and how fast it is moving.

Everything here is about one number: the Doppler frequency a scatterer puts on
the signal, ``2 v_radial / lambda`` for a there-and-back path.  At 10 GHz the
wavelength is 30 mm, so one metre per second is 67 Hz -- which is why rain
scatter on this band sounds like hissing rather than like a tone, and why a
mode that works on 2 m does not survive here at all.

Nothing in this module is a fixed curve.  Drops are sampled one at a time from
a size distribution, weighted by their own radar cross section, and given their
own fall speed and their own share of the turbulence, so no two renders see the
same rain.
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


@dataclass
class RainSpec:
    """A volume of falling rain, seen by two stations pointed into it."""

    rate_mm_h: float = 12.0
    elevation_deg: float = 8.0       # elevation of the common volume
    wind_mps: float = 6.0            # horizontal wind through the volume
    wind_azimuth_deg: float | None = None   # None: drawn at random per render
    turbulence_mps: float = 2.5      # velocity spread inside the volume
    path_km: float = 0.0             # rain along the path, for attenuation
    drops: int = 6000                # how many scatterers to sample


@dataclass
class SnowSpec:
    """Snow: slower, weaker, and brighter the moment it starts melting."""

    rate_mm_h: float = 4.0           # water equivalent
    wet: bool = False                # melting layer, the radar bright band
    elevation_deg: float = 8.0
    wind_mps: float = 5.0
    wind_azimuth_deg: float | None = None
    turbulence_mps: float = 0.9
    path_km: float = 0.0
    flakes: int = 6000


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


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """Median of ``values`` weighted by how hard each one scatters."""
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(cumulative, 0.5 * cumulative[-1])])


def _wind_radial(spec_wind: float, azimuth_deg: float | None, elevation_deg: float,
                 rng: np.random.Generator) -> tuple[float, float]:
    """Radial component of the wind, and the azimuth actually used."""
    azimuth = float(rng.uniform(0.0, 360.0)) if azimuth_deg is None else float(azimuth_deg)
    radial = spec_wind * np.cos(np.radians(azimuth)) * np.cos(np.radians(elevation_deg))
    return float(radial), azimuth


def rain_doppler(spec: RainSpec, band: Band, rng: np.random.Generator):
    """Sample a raining volume: Doppler frequencies and their weights.

    Sizes come from Marshall-Palmer (``N(D) = N0 exp(-4.1 R^-0.21 D)``), fall
    speeds from Atlas-Ulbrich (``v = 9.65 - 10.3 exp(-0.6 D)`` m/s), and each
    drop is weighted by ``D^6`` because that is how hard it scatters.
    """
    rate = max(spec.rate_mm_h, 0.01)
    lam = 4.1 * rate**-0.21                       # 1/mm
    diameters = rng.exponential(1.0 / lam, size=spec.drops)
    diameters = np.clip(diameters, 0.1, 7.0)      # mm, the drops that exist
    fall = np.clip(9.65 - 10.3 * np.exp(-0.6 * diameters), 0.2, 10.0)

    wind_radial, azimuth = _wind_radial(
        spec.wind_mps, spec.wind_azimuth_deg, spec.elevation_deg, rng)
    turbulence = rng.normal(0.0, max(spec.turbulence_mps, 0.0), size=spec.drops)
    radial = fall * np.sin(np.radians(spec.elevation_deg)) + wind_radial + turbulence

    freqs = np.asarray(band.doppler_hz(radial), dtype=np.float64)
    weights = diameters**6.0
    weights /= weights.sum()

    mean = float(np.sum(freqs * weights))
    spread = float(np.sqrt(np.sum(weights * (freqs - mean) ** 2)))
    info = {
        "kind": "rain",
        "rate_mm_h": rate,
        "dbz": reflectivity_dbz(rate),
        "median_drop_mm": _weighted_median(diameters, weights),
        "wind_azimuth_deg": azimuth,
        "wind_radial_mps": wind_radial,
        "shift_hz": mean,
        "spread_hz": spread,
        "scatterers": int(spec.drops),
        "attenuation_db": rain_attenuation_db_km(rate, band) * max(spec.path_km, 0.0),
    }
    return freqs, weights, info


def snow_doppler(spec: SnowSpec, band: Band, rng: np.random.Generator):
    """Sample falling snow.

    Aggregate sizes follow Gunn-Marshall (``Lambda = 25.5 R^-0.48`` on melted
    diameter) and fall at around a metre a second however big they are, so the
    spread is narrower than rain and the wind does most of the work.  Dry
    snowflakes are poor scatterers -- the ice dielectric factor alone costs
    about 6.5 dB -- while wet ones in the melting layer are brighter than the
    equivalent rain.
    """
    rate = max(spec.rate_mm_h, 0.01)
    lam = 25.5 * rate**-0.48
    diameters = np.clip(rng.exponential(1.0 / lam, size=spec.flakes), 0.1, 8.0)
    # Aggregates: v ~ 0.8 D^0.16, a metre a second give or take.
    fall = np.clip(0.8 * diameters**0.16 * (1.6 if spec.wet else 1.0), 0.2, 3.0)

    wind_radial, azimuth = _wind_radial(
        spec.wind_mps, spec.wind_azimuth_deg, spec.elevation_deg, rng)
    turbulence = rng.normal(0.0, max(spec.turbulence_mps, 0.0), size=spec.flakes)
    radial = fall * np.sin(np.radians(spec.elevation_deg)) + wind_radial + turbulence

    freqs = np.asarray(band.doppler_hz(radial), dtype=np.float64)
    weights = diameters**6.0
    weights /= weights.sum()

    mean = float(np.sum(freqs * weights))
    spread = float(np.sqrt(np.sum(weights * (freqs - mean) ** 2)))
    ice_db = 3.0 if spec.wet else -6.5
    info = {
        "kind": "wet snow" if spec.wet else "snow",
        "rate_mm_h": rate,
        "dbz": reflectivity_dbz(rate) + ice_db,
        "median_melted_mm": _weighted_median(diameters, weights),
        "wind_azimuth_deg": azimuth,
        "wind_radial_mps": wind_radial,
        "shift_hz": mean,
        "spread_hz": spread,
        "scatterers": int(spec.flakes),
        "relative_db": ice_db,
        "attenuation_db": rain_attenuation_db_km(rate * (0.6 if spec.wet else 0.25), band)
        * max(spec.path_km, 0.0),
    }
    return freqs, weights, info


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

    mean = float(np.sum(freqs * weights))
    spread_hz = float(np.sqrt(np.sum(weights * (freqs - mean) ** 2)))
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
