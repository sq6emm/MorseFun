"""Aircraft scatter: one reflector, moving fast, in the beam for a minute.

Nothing else on the microwave bands sounds like this.  A rain cell is a
population of scatterers and comes back as a hiss; an airliner is a single lump
of metal 60 m long doing 250 m/s, so it comes back as a *tone that slides*.  The
Doppler is bistatic, as always,

    f = (v . u_a + v . u_b) / lambda

but ``v`` is now one velocity rather than a distribution, and the two unit
vectors swing round as the aeroplane crosses between the stations.  It arrives
high, slides down through zero as it passes the middle of the path, and goes out
the other side, while the strength rises and falls with ``1 / (R_a R_b)^2`` and
with how far off each antenna's beam it is.  At 10 GHz the slide is hundreds of
Hz over a minute or two; on 2 m the same aeroplane moves the note by a few Hz and
nobody notices.

The aeroplane is not quite a point: it is tens of metres across and its aspect
turns slowly, so a handful of reflecting parts come back at slightly different
Doppler.  That is a spread of a few Hz at 10 GHz, which is the roughness on an
otherwise clean note, and it is modelled as the limb speed of something ``L``
long turning at the rate the geometry gives it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .propagation import Band

#: What is up there: a jet at cruise, and the extremes of a drawn one.
SPEED_RANGE = (180.0, 290.0)        # m/s
ALTITUDE_RANGE = (7.0, 12.5)        # km
LENGTH_RANGE = (25.0, 75.0)         # m, nose to tail


@dataclass
class AircraftSpec:
    """One aeroplane, and the two stations trying to use it."""

    baseline_km: float = 300.0        # how far apart the stations are
    altitude_km: float = 10.0
    speed_mps: float = 250.0
    heading_deg: float = 90.0         # 90 is straight across the path
    offset_km: float = 0.0            # where it crosses, from the midpoint
    miss_km: float = 0.0              # how far to the side of the path it passes
    length_m: float = 55.0            # how long the reflector is
    beamwidth_deg: float = 6.0        # each station's beam, pointed at the middle
    pass_s: float | None = None       # how long to watch; None is the whole render


def draw_aircraft(rng: np.random.Generator, **pinned) -> AircraftSpec:
    """Draw an aeroplane and a path for it to cross.  Pinned values are kept."""
    spec = AircraftSpec(**{k: v for k, v in pinned.items() if v is not None})
    drawn = {k: v for k, v in pinned.items() if v is not None}
    if "baseline_km" not in drawn:
        spec.baseline_km = float(rng.uniform(120.0, 600.0))
    if "altitude_km" not in drawn:
        spec.altitude_km = float(rng.uniform(*ALTITUDE_RANGE))
    if "speed_mps" not in drawn:
        spec.speed_mps = float(rng.uniform(*SPEED_RANGE))
    if "heading_deg" not in drawn:
        # Mostly crossing rather than following the path: that is what makes the
        # note slide.  Airways do run along paths, and then nothing much happens.
        spec.heading_deg = float(rng.normal(90.0, 35.0))
    if "offset_km" not in drawn:
        spec.offset_km = float(rng.normal(0.0, 0.1 * spec.baseline_km))
    if "miss_km" not in drawn:
        spec.miss_km = float(rng.normal(0.0, 12.0))
    if "length_m" not in drawn:
        spec.length_m = float(rng.uniform(*LENGTH_RANGE))
    if "beamwidth_deg" not in drawn:
        spec.beamwidth_deg = float(rng.uniform(2.0, 12.0))
    return spec


def _beam(angle_deg: np.ndarray, beamwidth_deg: float) -> np.ndarray:
    """Gaussian beam, -3 dB at half the beamwidth, in power."""
    half = max(beamwidth_deg, 0.1) / 2.0
    return np.exp(-np.log(2.0) * (angle_deg / half) ** 2)


def aircraft_track(spec: AircraftSpec, band: Band, seconds: float,
                   ticks: int = 400):
    """The pass, sampled in time: ``(times, doppler_hz, level, spread_hz, info)``.

    Levels come back normalised to the strongest moment, because what is wanted
    here is the shape of the pass; how loud it is in absolute terms is what
    ``--snr`` is for.
    """
    seconds = max(float(seconds), 1.0)
    times = np.linspace(0.0, seconds, max(int(ticks), 8))
    middle = 0.5 * seconds

    half = spec.baseline_km * 500.0                       # metres, each way
    a = np.array([-half, 0.0, 0.0])
    b = np.array([half, 0.0, 0.0])
    heading = np.radians(spec.heading_deg)
    velocity = spec.speed_mps * np.array([np.cos(heading), np.sin(heading), 0.0])
    start = np.array([spec.offset_km * 1000.0, spec.miss_km * 1000.0,
                      spec.altitude_km * 1000.0]) - velocity * middle
    position = start[:, None] + velocity[:, None] * times[None, :]

    to_a = a[:, None] - position
    to_b = b[:, None] - position
    range_a = np.linalg.norm(to_a, axis=0)
    range_b = np.linalg.norm(to_b, axis=0)
    unit_a, unit_b = to_a / range_a, to_b / range_b
    closing = np.sum(velocity[:, None] * (unit_a + unit_b), axis=0)
    doppler = np.asarray(band.bistatic_doppler_hz(closing))

    # Both stations beam along the path, so the level falls away as the aeroplane
    # moves off that line, and with the fourth power of the ranges.
    # Off-boresight angle: each station points at the other, and what matters is
    # the angle between that heading and the direction *out* to the aeroplane,
    # which is the unit vector back from it reversed.
    toward_b = (b - a) / np.linalg.norm(b - a)
    angle_a = np.degrees(np.arccos(np.clip(
        np.sum(-unit_a * toward_b[:, None], axis=0), -1, 1)))
    angle_b = np.degrees(np.arccos(np.clip(
        np.sum(-unit_b * -toward_b[:, None], axis=0), -1, 1)))
    power = (_beam(angle_a, spec.beamwidth_deg) * _beam(angle_b, spec.beamwidth_deg)
             / (range_a**2 * range_b**2))
    level = np.sqrt(power / max(float(power.max()), 1e-30))

    # An extended reflector turning: the far parts of it answer at their own
    # Doppler, which is the roughness on the note.
    turn = np.linalg.norm(np.cross(velocity, unit_a.T).T, axis=0) / range_a
    spread = np.abs(np.asarray(band.doppler_hz(turn * spec.length_m / 2.0)))

    peak = int(np.argmax(power))
    loud = level > 10.0 ** (-10.0 / 20.0)
    sweep = float(np.gradient(doppler, times)[peak])
    info = {
        "kind": "aircraft",
        "baseline_km": spec.baseline_km,
        "altitude_km": spec.altitude_km,
        "speed_mps": spec.speed_mps,
        "heading_deg": spec.heading_deg,
        "length_m": spec.length_m,
        "beamwidth_deg": spec.beamwidth_deg,
        "shift_hz": float(doppler[peak]),
        "doppler_from_hz": float(doppler[0]),
        "doppler_to_hz": float(doppler[-1]),
        "sweep_hz_s": sweep,
        "spread_hz": float(spread[peak]),
        "best_at_s": float(times[peak]),
        "window_s": float(times[loud][-1] - times[loud][0]) if loud.any() else 0.0,
        "range_km": float((range_a[peak] + range_b[peak]) / 1000.0),
        "scatterers": 1,
        "attenuation_db": 0.0,
    }
    return times, doppler, level, spread, info
