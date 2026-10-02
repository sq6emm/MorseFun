"""A skywave path on a low band, seen through a filter a few milliHertz wide.

At 137 kHz the wavelength is 2.2 km, so a metre per second of motion is 0.9
milliHertz: nothing, by any normal measure.  QRSS is not a normal measure.  A
three-second dit is read in a bin a third of a Hz wide, a two-minute dit in a
bin of about ten milliHertz, and at that resolution the ionosphere is visibly
alive -- which is why a 2200 m trace is drawn as a hair while the same message
on 30 m comes out as a fuzzy band that wanders.

What is modelled is the one thing that matters at these wavelengths: the
reflecting layer moves up and down.  A one-hop path gets longer by twice the
height change times the sine of the take-off angle, so

    f = 2 (dh/dt) sin(elevation) / lambda

Overnight that is a few tenths of a metre per second; at dawn and dusk the
layer can run at several metres a second, which on 30 m is a couple of tenths
of a Hz -- wide enough to smear a QRSS30 trace, and still only a milliHertz or
two on 2200 m.  Irregularities inside the layer spread each ray a little
further, and a path that arrives by more than one mode or hop arrives at more
than one Doppler: those beat, and that beat is the slow QSB a QRSS screen
shows as the trace fading in and out of its own shadow.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .propagation import Band, moments
from .scatter import Carrier

#: How fast the reflecting height moves: a quiet night, and a dawn transition.
HEIGHT_RATE_RANGE = (0.05, 5.0)

MAX_MODES = 3


@dataclass
class Mode:
    """One way the signal got here: its layer motion and its share of the power."""

    height_rate_mps: float = 0.3      # upwards is positive
    turbulence_mps: float = 0.2       # spread of vertical motions in the patch
    power: float = 1.0                # share of the arriving signal
    fade_rate_hz: float = 0.01        # how fast its own level wanders
    fade_db: float = 4.0


@dataclass
class IonoSpec:
    """A low-band skywave path: a layer that moves, arriving more than one way."""

    modes: list[Mode] = field(default_factory=lambda: [Mode()])
    elevation_deg: float = 30.0        # take-off angle at the reflection point
    wander_rate_hz: float = 0.004      # how fast the layer motion itself changes
    wander_mps: float = 0.2
    rays: int = 3000


def draw_iono(rng: np.random.Generator, band: Band, *, modes: int | None = None,
              height_rate_mps: float | None = None,
              turbulence_mps: float | None = None,
              elevation_deg: float | None = None,
              wander_mps: float | None = None,
              wander_rate_hz: float | None = None) -> IonoSpec:
    """Draw a path: how the layer is moving tonight, and how many ways in."""
    count = (int(np.clip(modes, 1, MAX_MODES)) if modes is not None
             else int(np.clip(1 + rng.poisson(0.8), 1, MAX_MODES)))
    if height_rate_mps is not None:
        bulk = float(height_rate_mps)
    else:
        lo, hi = HEIGHT_RATE_RANGE
        bulk = float(np.exp(rng.uniform(np.log(lo), np.log(hi)))
                     * (1.0 if rng.random() < 0.5 else -1.0))
    churn = (float(turbulence_mps) if turbulence_mps is not None
             else float(np.exp(rng.uniform(np.log(0.05), np.log(1.5)))))
    powers = rng.lognormal(0.0, 0.7, size=count)
    powers /= powers.sum()
    drawn = [
        Mode(
            # Each hop or magneto-ionic component sees its own bit of layer --
            # unless there is only one, in which case it sees all of it.
            height_rate_mps=float(bulk if count == 1 else
                                  bulk + rng.normal(0.0, 0.35 * abs(bulk) + 0.05)),
            turbulence_mps=float(max(churn * rng.lognormal(0.0, 0.3), 0.0)),
            power=float(power),
            fade_rate_hz=float(rng.uniform(0.002, 0.05)),
            fade_db=float(rng.uniform(2.0, 12.0)),
        )
        for power in powers
    ]
    return IonoSpec(
        modes=drawn,
        elevation_deg=(float(elevation_deg) if elevation_deg is not None
                       else float(rng.uniform(15.0, 60.0))),
        wander_mps=(float(wander_mps) if wander_mps is not None
                    else float(abs(bulk) * rng.uniform(0.2, 0.8) + 0.05)),
        wander_rate_hz=(float(wander_rate_hz) if wander_rate_hz is not None
                        else float(rng.uniform(0.001, 0.02))),
    )


def iono_carriers(spec: IonoSpec, band: Band):
    """Turn the path into the carriers that arrive.  Returns ``(carriers, info)``.

    One per mode, each with the Doppler its own bit of layer gives it and a
    wander of the same order; their beat is left to the sum.
    """
    lift = float(np.sin(np.radians(spec.elevation_deg)))
    carriers: list[Carrier] = []
    detail: list[dict[str, float]] = []
    for mode in spec.modes:
        shift = float(band.doppler_hz(mode.height_rate_mps * lift))
        wander = float(band.doppler_hz((mode.turbulence_mps + spec.wander_mps) * lift))
        carriers.append(Carrier(
            shift_hz=shift,
            spread_hz=wander,
            wander_rate_hz=spec.wander_rate_hz,
            level=float(np.sqrt(mode.power)),
            fade_db=mode.fade_db,
            fade_rate_hz=mode.fade_rate_hz,
        ))
        detail.append({"shift_hz": shift, "wander_hz": wander,
                       "height_rate_mps": mode.height_rate_mps,
                       "level_db": 10.0 * float(np.log10(max(mode.power, 1e-9)))})

    weights = np.array([c.level**2 for c in carriers])
    shifts = np.array([c.shift_hz for c in carriers])
    shift, between = moments(shifts, weights)
    wander = float(np.sum(weights * np.array([c.spread_hz for c in carriers]))
                   / max(float(weights.sum()), 1e-12))
    gaps = [abs(a - b) for i, a in enumerate(shifts) for b in shifts[i + 1:]]
    beat = float(min(gaps)) if gaps else 0.0
    info = {
        "kind": "skywave",
        "modes": detail,
        "elevation_deg": spec.elevation_deg,
        "height_rate_mps": float(np.sum(weights * np.array(
            [m.height_rate_mps for m in spec.modes])) / max(float(weights.sum()), 1e-12)),
        "turbulence_mps": float(np.mean([m.turbulence_mps for m in spec.modes])),
        "wander_mps": spec.wander_mps,
        "beat_hz": beat,
        "fade_period_s": (1.0 / beat) if beat > 1e-9 else 0.0,
        "shift_hz": shift,
        # What the trace is worth on a waterfall: how far it wanders, plus how
        # far the modes sit apart.
        "spread_hz": float(np.hypot(wander, between)),
        "wander_hz": wander,
        "between_hz": between,
        "scatterers": len(carriers),
        "attenuation_db": 0.0,
    }
    return carriers, info
