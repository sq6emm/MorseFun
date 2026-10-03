"""The Moon as a reflector: 2.5 seconds away, and never holding still.

An EME echo is the sum of returns from the whole visible face, so it is the
same kind of thing as a rain cell -- a population of scatterers, each with its
own Doppler -- with the geometry replaced by a sphere 1738 km across.  What
moves them is **libration**: the Moon's apparent rotation as seen from the
station, a couple of degrees a day of optical libration plus the diurnal part
from the observer being carried around by the Earth.  One limb comes towards
you and the other goes away, so the echo comes back spread:

    limb speed = omega * R,   spread ~ 2 * omega * R / lambda

That is the limb-to-limb figure: a quiet 0.2 deg/day puts the limbs 0.07 Hz
apart on 2 m and 5 Hz apart on 10 GHz, a busy 8 deg/day 3 Hz and 230 Hz.  The
rms spread of the echo, which is what the report quotes and what a bin has to
hold, is about 0.4 of that with the disc weighted towards its middle: 0.03 Hz
and 1.8 Hz at the quiet end.  Operators watch for the days
when that number is small and call it libration minimum, and this is why: the
spread cannot be tuned out, and once it is wider than the bin a QRSS trace is
being integrated in, the trace smears and the processing gain goes with it.

Three more things the path does, all reported:

* **Delay.** 356 500 to 406 700 km each way, so the echo arrives 2.38 to 2.71 s
  after it was keyed.  On an echo test you hear your own keying, then it again.
* **Doppler.** The station is carried around the Earth at up to 465 m/s, which
  on 2 m is ±450 Hz and on 10 GHz ±30 kHz, and it *changes* by up to a few
  hundredths of a Hz per second -- tens of Hz across a QRSS message.  Real
  stations track it; so does this, unless told not to.
* **Faraday rotation** on VHF: the plane of polarisation turns as the TEC
  changes, so the echo fades to nothing and comes back over minutes.  It goes
  as 1/f^2, so it is a 2 m and 70 cm problem and nothing at 10 GHz.

What is not modelled: the depth of the Moon is 11.6 ms of delay spread between
the sub-radar point and the limb, which smears fast CW and is neither here nor
there at QRSS speeds.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dsp import smooth_noise
from .propagation import C, Band, moments

MOON_RADIUS_M = 1_737_400.0
PERIGEE_KM = 356_500.0
APOGEE_KM = 406_700.0

#: How fast a point on the equator is carried east, m/s.  The station's range
#: rate to the Moon is this, projected, so it bounds the self-Doppler.
EARTH_SURFACE_MPS = 465.0

#: Libration, degrees a day: the quiet end operators wait for, and a busy day.
LIBRATION_RANGE = (0.2, 8.0)


@dataclass
class MoonSpec:
    """Where the Moon is, how fast it appears to turn, and how it is seen."""

    distance_km: float | None = None        # drawn between perigee and apogee
    libration_deg_day: float | None = None  # apparent rotation rate
    range_rate_mps: float | None = None     # towards us is positive
    range_accel_mps2: float | None = None   # how fast that is changing
    scatter_law: float | None = None        # cos^n weighting across the disc
    faraday_db: float | None = None         # depth of the polarisation fade
    faraday_period_s: float | None = None
    track: bool = True                      # tune the Doppler out as it moves
    patches: int = 4000

    @property
    def delay_s(self) -> float:
        return 2.0 * (self.distance_km or APOGEE_KM) * 1000.0 / C


def draw_moon(rng: np.random.Generator, band: Band, **pinned) -> MoonSpec:
    """Draw a moonrise: distance, libration, own Doppler, and the polarisation.

    Anything passed in is kept.  Faraday depth follows the band, because it has
    to: the rotation goes as 1/f^2, so what wipes out a 2 m echo for minutes at
    a time is not worth mentioning on 23 cm and does not exist on 10 GHz.
    """
    spec = MoonSpec(**{k: v for k, v in pinned.items() if v is not None})
    if spec.distance_km is None:
        spec.distance_km = float(rng.uniform(PERIGEE_KM, APOGEE_KM))
    if spec.libration_deg_day is None:
        lo, hi = LIBRATION_RANGE
        spec.libration_deg_day = float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
    if spec.range_rate_mps is None:
        # Mostly the Earth turning under the station, plus the orbit itself.
        spec.range_rate_mps = float(rng.uniform(-1.0, 1.0) * EARTH_SURFACE_MPS
                                    + rng.normal(0.0, 30.0))
    if spec.range_accel_mps2 is None:
        # d/dt of the above: the Earth's rotation rate times its surface speed.
        peak = 7.292e-5 * EARTH_SURFACE_MPS
        spec.range_accel_mps2 = float(rng.uniform(-peak, peak))
    if spec.scatter_law is None:
        # Quasi-specular: the sub-radar point answers far louder than the limb.
        spec.scatter_law = float(rng.uniform(1.5, 3.0))
    if spec.faraday_db is None:
        reference = 144e6 / max(band.hz, 1.0)
        depth = float(np.clip(22.0 * reference**2, 0.0, 25.0))
        spec.faraday_db = depth if depth >= 0.5 else 0.0
    if spec.faraday_period_s is None:
        spec.faraday_period_s = float(rng.uniform(180.0, 1500.0))
    return spec


def libration_rate_rad_s(deg_day: float) -> float:
    return float(np.radians(deg_day) / 86400.0)


def moon_doppler(spec: MoonSpec, band: Band, rng: np.random.Generator):
    """Sample the visible face: one Doppler frequency and weight per patch.

    Patches are spread over the disc, weighted by ``cos^n`` of the angle from
    the sub-radar point -- the Moon answers from the middle far more than from
    the edge -- and given the speed that libration carries them at.
    """
    count = max(int(spec.patches), 64)
    radius = np.sqrt(rng.random(count))            # uniform over the disc
    angle = rng.uniform(0.0, 2 * np.pi, size=count)
    along = radius * np.cos(angle)                 # across the libration axis
    tilt = np.sqrt(np.clip(1.0 - radius**2, 0.0, 1.0))   # cos of the angle out

    omega = libration_rate_rad_s(spec.libration_deg_day or 0.0)
    velocity = omega * MOON_RADIUS_M * along
    freqs = np.asarray(band.doppler_hz(velocity), dtype=np.float64)
    weights = np.power(tilt, max(spec.scatter_law or 2.0, 0.0))
    total = float(weights.sum())
    weights = weights / total if total > 0 else np.full(count, 1.0 / count)

    shift, spread = moments(freqs, weights)
    own = float(band.doppler_hz(spec.range_rate_mps or 0.0))
    info = {
        "kind": "moon",
        "distance_km": spec.distance_km,
        "delay_s": spec.delay_s,
        "libration_deg_day": spec.libration_deg_day,
        "limb_hz": float(band.doppler_hz(omega * MOON_RADIUS_M)),
        "scatter_law": spec.scatter_law,
        "own_doppler_hz": own,
        "drift_hz_s": float(band.doppler_hz(spec.range_accel_mps2 or 0.0)),
        "range_rate_mps": spec.range_rate_mps,
        "tracking": bool(spec.track),
        "faraday_db": spec.faraday_db,
        "faraday_period_s": spec.faraday_period_s,
        "shift_hz": shift + (0.0 if spec.track else own),
        "spread_hz": spread,
        "scatterers": count,
        "attenuation_db": 0.0,
    }
    return freqs, weights, info


def faraday_fade(n: int, sample_rate: int, rng: np.random.Generator,
                 depth_db: float, period_s: float) -> np.ndarray:
    """Polarisation fading: ``cos`` nulls, minutes apart, as the TEC drifts.

    Not a random walk like the rest of the fading in this program -- Faraday
    rotation turns steadily and takes the signal down to nothing when the two
    ends are crossed, which is why VHF EME operators wait a fade out rather
    than call again.
    """
    if n == 0 or depth_db <= 0:
        return np.ones(max(n, 0))
    t = np.arange(n) / sample_rate
    wander = smooth_noise(n, sample_rate, 1.0 / max(period_s * 4, 1.0), rng)
    phase = 2 * np.pi * t / max(period_s, 1.0) + 0.6 * np.pi * wander
    floor = 10.0 ** (-abs(depth_db) / 20.0)
    return floor + (1.0 - floor) * np.abs(np.cos(phase))
