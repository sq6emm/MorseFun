"""A rain cell is not a filter: it has a shape, cores, and its own geometry.

Two stations on a microwave band share a volume where their beams cross inside
the weather, and everything audible about a rain-scattered signal comes out of
that volume: how high it is, how steeply each end looks into it, how far the
cell sits off the line between them, which way the wind blows through it, and
how hard the air inside it is going up and down.

Scattering is bistatic, so the closing speed towards *both* ends counts:

    f = (v . u_a + v . u_b) / lambda

with ``u_a`` and ``u_b`` the unit vectors from the scatterer to the two
stations.  Their sum is ``2 cos(beta/2)`` long and points along the bisector of
the two paths, which for two stations looking into the same cloud at the same
elevation is straight *up*.  That one fact is the whole character of rain
scatter.  What is heard is the vertical motion inside the cell -- the fall speed
of the drops, the updraught of a core, the churn around it -- scaled by the
elevation; the wind largely cancels between the two ends, and only gets in when
the path is lopsided or the cell sits off to one side.  Raise the elevation, or
put the cell somewhere else, and the same rain sounds like a different mode.

So nothing here is fixed.  A cell is *drawn*: a character somewhere between
flat stratiform rain and a deep convective core, as many cores as that
character deserves, each with its own rate, updraught, size and place in the
beam, the turbulence, the wind shear through the volume, the geometry the two
ends see it with, and how fast all of it changes while the message is being
sent.  Two renders are two different fronts -- one nearly clean CW with a
flutter on it, the next a rasp no narrower than aurora -- and with ``--seed``
a front can be visited again.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .dsp import smooth_noise
from .propagation import (Band, drop_diameters, drop_fall_speed, flake_diameters,
                          flake_fall_speed, moments, rain_attenuation_db_km,
                          reflectivity_dbz, weighted_median)
from .scatter import Component

#: The character axis: 0 is flat stratiform rain, 1 a deep convective core.
#: Everything else about a cell is drawn from it, starting with the rain rate.
CHARACTER_RATES = (1.2, 85.0)        # mm/h at character 0 and 1

CHARACTER_NAMES = (
    (0.25, "stratiform"),     # under about 3.5 mm/h: layered, quiet air
    (0.55, "showers"),        # to about 14 mm/h
    (0.82, "convective"),     # to about 40 mm/h: cores, lift, shear
    (1.01, "storm"),          # a downpour with everything moving
)

#: What each name means on that axis, for ``--cell convective``.
CHARACTER_VALUES = {
    "stratiform": 0.12,
    "showers": 0.40,
    "convective": 0.68,
    "storm": 0.93,
}

MAX_CORES = 4


def character_name(character: float) -> str:
    for limit, name in CHARACTER_NAMES:
        if character < limit:
            return name
    return CHARACTER_NAMES[-1][1]


def parse_character(text: str | float | None) -> float | None:
    """``auto``, a name like ``convective``, or a number from 0 to 1."""
    if text is None or isinstance(text, (int, float)):
        return None if text is None else float(np.clip(float(text), 0.0, 1.0))
    token = str(text).strip().lower()
    if token in ("", "auto", "random", "draw"):
        return None
    matches = [v for name, v in CHARACTER_VALUES.items() if name.startswith(token)]
    if len(matches) == 1:
        return matches[0]
    try:
        value = float(token)
    except ValueError:
        raise ValueError(
            f"unknown cell character {text!r}: use auto, "
            + ", ".join(sorted(CHARACTER_VALUES)) + ", or 0..1") from None
    return float(np.clip(value, 0.0, 1.0))


def rate_from_character(character: float, rng: np.random.Generator | None = None) -> float:
    lo, hi = CHARACTER_RATES
    rate = lo * (hi / lo) ** float(np.clip(character, 0.0, 1.0))
    if rng is not None:
        rate *= float(rng.lognormal(0.0, 0.22))
    return float(rate)


def character_from_rate(rate_mm_h: float, rng: np.random.Generator | None = None) -> float:
    """A rain rate implies a kind of cloud: 2 mm/h is layered, 60 mm/h is a core."""
    lo, hi = CHARACTER_RATES
    character = float(np.log(max(rate_mm_h, 0.05) / lo) / np.log(hi / lo))
    if rng is not None:
        character += float(rng.normal(0.0, 0.1))
    return float(np.clip(character, 0.0, 1.0))


def _lerp_log(lo: float, hi: float, t: float) -> float:
    return float(np.exp(np.log(lo) + (np.log(hi) - np.log(lo)) * float(np.clip(t, 0.0, 1.0))))


@dataclass(frozen=True)
class Geometry:
    """Where the common volume is, and how the two ends look into it.

    The volume sits at the origin; both stations are on the ground, ours in the
    ``+x`` direction and the other one roughly opposite, off by ``squint_deg``.
    Elevations are what each station's antenna is pointed at, and they are what
    decides how much of the vertical motion inside the cell is heard: the
    sensitivity of the pair is ``cos(beta/2)``, which for a symmetric path is
    exactly ``sin(elevation)``.
    """

    elevation_deg: float = 6.0        # our end
    far_elevation_deg: float = 6.0    # the other end
    squint_deg: float = 0.0           # cell off the line between the stations
    height_km: float = 3.0            # height of the common volume
    beamwidth_deg: float = 1.8        # antenna beamwidth, so how big the volume is
    depth_km: float = 1.5             # how deep a slice of weather is sampled

    @property
    def near_range_km(self) -> float:
        return self.height_km / max(np.sin(np.radians(self.elevation_deg)), 1e-3)

    @property
    def far_range_km(self) -> float:
        return self.height_km / max(np.sin(np.radians(self.far_elevation_deg)), 1e-3)

    @property
    def baseline_km(self) -> float:
        """How far apart the two stations are, along the ground."""
        near = self.near_range_km * np.cos(np.radians(self.elevation_deg))
        far = self.far_range_km * np.cos(np.radians(self.far_elevation_deg))
        squint = np.radians(self.squint_deg)
        return float(np.hypot(near + far * np.cos(squint), far * np.sin(squint)))

    def stations(self) -> tuple[np.ndarray, np.ndarray]:
        """Both station positions in metres, with the volume at the origin."""
        near = self.near_range_km * np.cos(np.radians(self.elevation_deg)) * 1000.0
        far = self.far_range_km * np.cos(np.radians(self.far_elevation_deg)) * 1000.0
        squint = np.radians(self.squint_deg)
        height = self.height_km * 1000.0
        a = np.array([near, 0.0, -height])
        b = np.array([-far * np.cos(squint), -far * np.sin(squint), -height])
        return a, b

    @property
    def sensitivity(self) -> float:
        """``cos(beta/2)``: how much of a metre per second is heard at all."""
        a, b = self.stations()
        total = a / np.linalg.norm(a) + b / np.linalg.norm(b)
        return float(np.linalg.norm(total) / 2.0)

    @property
    def bistatic_angle_deg(self) -> float:
        """The angle the signal is bent through; 180 deg would be straight on."""
        a, b = self.stations()
        cosine = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
        return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))

    def blob_sigma_m(self) -> tuple[float, float, float]:
        """Size of the volume the beams share, as a Gaussian blob in metres.

        Across the beam it is simply the beamwidth at the shorter range.  Along
        the path it is far longer: two beams crossing at a shallow angle share a
        long cigar, which is why a low path hears so much more of the wind than
        a steep one does.  Vertically it is whichever is smaller, the beam or
        the slice of weather asked for.
        """
        beam = np.radians(max(self.beamwidth_deg, 0.05))
        reach = min(self.near_range_km, self.far_range_km) * 1000.0
        across = 0.5 * beam * reach
        mean_elevation = 0.5 * (self.elevation_deg + self.far_elevation_deg)
        along = across / max(np.tan(np.radians(mean_elevation)), 0.02)
        along = min(along, 0.35 * reach)
        upright = min(across, self.depth_km * 500.0)
        return float(along), float(across), float(upright)

    def closing_vectors(self, offsets: np.ndarray) -> np.ndarray:
        """``u_a + u_b`` for scatterers at ``offsets`` (3, n) metres from the centre."""
        a, b = self.stations()
        to_a = a[:, None] - offsets
        to_b = b[:, None] - offsets
        to_a /= np.linalg.norm(to_a, axis=0, keepdims=True)
        to_b /= np.linalg.norm(to_b, axis=0, keepdims=True)
        return to_a + to_b


@dataclass
class Core:
    """One scattering centre inside the cell: its rain, its air, its place."""

    rate_mm_h: float = 12.0
    updraft_mps: float = 0.0          # bulk vertical motion through it
    lift_gradient_mps_km: float = 0.0  # how fast that changes across the core
    turbulence_w_mps: float = 1.0     # vertical velocity spread
    turbulence_h_mps: float = 0.6     # horizontal velocity spread
    size_km: float = 8.0              # how wide the core is
    offset_km: float = 0.0            # how far along the beam it sits
    breathe_db: float = 3.0           # how much its level swings as it evolves
    breathe_rate_hz: float = 0.2
    wander_mps: float = 0.4           # how far its vertical motion wanders
    wander_rate_hz: float = 0.15
    width_swing: float = 0.2          # how much its spread breathes


@dataclass
class Cell:
    """A whole front: its cores, the volume geometry, and how fast it changes."""

    kind: str = "rain"                # rain | snow
    character: float = 0.4
    cores: list[Core] = field(default_factory=lambda: [Core()])
    geometry: Geometry = field(default_factory=Geometry)
    wind_mps: float = 8.0
    wind_azimuth_deg: float = 0.0     # measured from the bearing of our station
    shear_mps_km: float = 6.0         # how much the wind changes through the volume
    shear_azimuth_deg: float = 0.0
    wet: bool = False                 # snow only: the melting layer
    evolve_rate_hz: float = 0.2       # how fast the cell rearranges itself
    scintillation_db: float = 4.0     # slow fading on top of the Rayleigh flutter
    scintillation_rate_hz: float = 0.3

    @property
    def name(self) -> str:
        return character_name(self.character)

    @property
    def rate_mm_h(self) -> float:
        """The rate that matters: the cores weighted by how hard they scatter."""
        weights = [10.0 ** (reflectivity_dbz(c.rate_mm_h, self.kind, self.wet) / 10.0)
                   for c in self.cores]
        total = sum(weights)
        if total <= 0:
            return 0.0
        return float(sum(w * c.rate_mm_h for w, c in zip(weights, self.cores)) / total)

    def attenuation_db(self, band: Band, path_km: float) -> float:
        """What the weather on the way costs, in dB."""
        rate = self.rate_mm_h
        if self.kind == "snow":
            rate *= 0.6 if self.wet else 0.25
        return rain_attenuation_db_km(rate, band) * max(float(path_km), 0.0)


def draw_cell(
    rng: np.random.Generator,
    kind: str = "rain",
    *,
    character: float | None = None,
    rate_mm_h: float | None = None,
    cores: int | None = None,
    updraft_mps: float | None = None,
    turbulence_mps: float | None = None,
    shear_mps_km: float | None = None,
    wind_mps: float | None = None,
    wind_azimuth_deg: float | None = None,
    elevation_deg: float | None = None,
    squint_deg: float | None = None,
    beamwidth_deg: float | None = None,
    height_km: float | None = None,
    depth_km: float | None = None,
    evolve_rate_hz: float | None = None,
    scintillation_db: float | None = None,
    wet: bool = False,
) -> Cell:
    """Draw a cell.  Anything passed in is kept; everything else is sampled.

    Rain and snow are drawn from the same shape, with snow pinned near the
    stratiform end of the character axis -- it falls out of layered cloud, a
    metre a second, with little inside it to churn the air -- and at the low
    melted rates a snowfall actually has.
    """
    snow = str(kind).lower() == "snow"

    if character is not None:
        char = float(np.clip(character, 0.0, 1.0))
    elif rate_mm_h is not None and not snow:
        char = character_from_rate(rate_mm_h, rng)
    elif snow:
        char = float(np.clip(rng.beta(1.4, 6.0), 0.0, 0.45))
    else:
        char = float(rng.beta(1.1, 1.1))

    if rate_mm_h is not None:
        rate = float(max(rate_mm_h, 0.05))
    elif snow:
        # Melted-equivalent: a steady snowfall is a millimetre an hour or so,
        # and a heavy one two or three.
        rate = float(np.clip((0.4 + 2.5 * char) * rng.lognormal(0.0, 0.4), 0.2, 6.0))
    else:
        rate = rate_from_character(char, rng)

    count = MAX_CORES if cores is None else int(np.clip(cores, 1, MAX_CORES))
    if cores is None:
        drawn = 1 + int(rng.poisson(1.0 if snow else 1.6 * char**1.5))
        count = int(np.clip(drawn, 1, MAX_CORES))

    if turbulence_mps is not None:
        turbulence = float(max(turbulence_mps, 0.0))
    elif snow:
        turbulence = _lerp_log(0.2, 1.3, char / 0.45 if char else 0.0)
    else:
        turbulence = _lerp_log(0.25, 6.5, char) * float(rng.lognormal(0.0, 0.2))

    # Geometry.  Elevation is drawn on its own: it is the path, not the weather,
    # and it is the single biggest reason two stations on the same cell sound
    # nothing alike.
    elevation = (float(elevation_deg) if elevation_deg is not None
                 else _lerp_log(1.0, 25.0, float(rng.random())))
    # The cell is hardly ever halfway: it sits over one of the two stations more
    # than the other, which tilts the bisector away from the vertical and lets
    # the wind in.  A lopsided path is a rough-sounding path.
    far_elevation = float(np.clip(elevation * rng.lognormal(0.0, 0.75), 0.3, 50.0))
    squint = float(abs(rng.normal(0.0, 12.0))) if squint_deg is None else float(squint_deg)
    beamwidth = (float(beamwidth_deg) if beamwidth_deg is not None
                 else float(rng.uniform(0.9, 3.2)))
    if height_km is not None:
        height = float(height_km)
    else:
        ceiling = 2.0 + 5.0 * char if not snow else 1.2 + 1.8 * char
        height = float(np.clip(rng.uniform(0.8, 1.0 + ceiling), 0.5, 9.0))
    depth = (float(depth_km) if depth_km is not None
             else float(np.clip(rng.uniform(0.4, 1.0 + 2.5 * (0.4 + char)), 0.2, 4.0)))
    geometry = Geometry(
        elevation_deg=elevation, far_elevation_deg=far_elevation, squint_deg=squint,
        height_km=height, beamwidth_deg=beamwidth, depth_km=depth,
    )
    along_km = geometry.blob_sigma_m()[0] / 1000.0

    wind = (float(wind_mps) if wind_mps is not None
            else float(np.clip(2.0 + 30.0 * rng.beta(1.8, 2.4), 0.5, 40.0)))
    wind_azimuth = (float(rng.uniform(0.0, 360.0)) if wind_azimuth_deg is None
                    else float(wind_azimuth_deg))
    shear = (float(shear_mps_km) if shear_mps_km is not None
             else float((0.5 + (6.0 if snow else 24.0) * char) * rng.lognormal(0.0, 0.35)))
    shear_azimuth = float(wind_azimuth + rng.normal(0.0, 40.0))

    evolve = (float(evolve_rate_hz) if evolve_rate_hz is not None
              else _lerp_log(0.03, 0.15 if snow else 0.8, char))
    scint = (float(scintillation_db) if scintillation_db is not None
             else float((1.0 + (4.0 if snow else 11.0) * char**1.3) * rng.uniform(0.7, 1.3)))

    drawn_cores: list[Core] = []
    for index in range(count):
        core_rate = rate if count == 1 else float(
            np.clip(rate * rng.lognormal(0.0, 0.3 * (0.3 + char)), 0.05, 180.0))
        if updraft_mps is not None:
            updraft = float(updraft_mps)
        elif snow:
            updraft = float(np.clip(rng.normal(0.0, 0.3 + 0.8 * char), -2.0, 2.0))
        else:
            updraft = float(np.clip(rng.normal(0.0, 0.6 + 9.0 * char**1.6), -16.0, 20.0))
        turb_w = float(max(turbulence * rng.lognormal(0.0, 0.25), 0.0))
        size = float(_lerp_log(25.0 if snow else 18.0, 2.5, char) * rng.lognormal(0.0, 0.35))
        offset = 0.0 if index == 0 else float(rng.normal(0.0, 0.7 * max(along_km, 0.3)))
        drawn_cores.append(Core(
            rate_mm_h=core_rate,
            updraft_mps=updraft,
            lift_gradient_mps_km=float(
                (0.05 + (0.4 if snow else 5.0) * char**1.5) * rng.lognormal(0.0, 0.4)
                * (1.0 if rng.random() < 0.5 else -1.0)),
            turbulence_w_mps=turb_w,
            turbulence_h_mps=float(turb_w * rng.uniform(0.4, 0.9)),
            size_km=size,
            offset_km=offset,
            breathe_db=float((1.0 + (3.0 if snow else 11.0) * char**1.2) * rng.uniform(0.7, 1.4)),
            breathe_rate_hz=float(evolve * rng.uniform(0.6, 1.8)),
            wander_mps=float((0.1 + (0.6 if snow else 3.5) * char**1.5) * rng.uniform(0.6, 1.5)),
            wander_rate_hz=float(evolve * rng.uniform(0.4, 1.2)),
            width_swing=float(0.1 + 0.35 * char),
        ))

    return Cell(
        kind="snow" if snow else "rain", character=char, cores=drawn_cores,
        geometry=geometry, wind_mps=wind, wind_azimuth_deg=wind_azimuth,
        shear_mps_km=shear, shear_azimuth_deg=shear_azimuth, wet=bool(wet),
        evolve_rate_hz=evolve, scintillation_db=scint,
        scintillation_rate_hz=float(np.clip(0.1 + 0.6 * char, 0.05, 1.2)),
    )


@dataclass
class CoreSample:
    """One core, sampled: every scatterer's Doppler and how hard it scatters."""

    core: Core
    freqs: np.ndarray
    weights: np.ndarray        # normalised across the whole cell
    sizes: np.ndarray          # drop or flake diameters, mm
    centre_hz: float
    spread_hz: float
    power: float               # this core's share of the return
    hz_per_mps: float          # how far its note moves per m/s of lift


def _core_velocities(cell: Cell, core: Core, count: int, rng: np.random.Generator):
    """Where the scatterers are, how fast they fall, and what the air does."""
    along, across, upright = cell.geometry.blob_sigma_m()
    limit = core.size_km * 500.0                      # half the core, in metres
    along = min(along, limit)
    across = min(across, limit)
    offsets = np.vstack([
        rng.normal(core.offset_km * 1000.0, max(along, 1.0), size=count),
        rng.normal(0.0, max(across, 1.0), size=count),
        rng.normal(0.0, max(upright, 1.0), size=count),
    ])

    if cell.kind == "snow":
        sizes = flake_diameters(core.rate_mm_h, count, rng)
        fall = flake_fall_speed(sizes, cell.wet)
    else:
        sizes = drop_diameters(core.rate_mm_h, count, rng)
        fall = drop_fall_speed(sizes)

    # A convective cell is going up in one place and raining out in another, so
    # the lift is not the same everywhere the beams pass through: that gradient,
    # across a volume kilometres long, is what makes a core sound like aurora.
    along_km = offsets[0] / 1000.0 - core.offset_km
    lift = np.clip(core.updraft_mps + core.lift_gradient_mps_km * along_km, -18.0, 22.0)
    height_km = offsets[2] / 1000.0
    wind = np.radians(cell.wind_azimuth_deg)
    shear = np.radians(cell.shear_azimuth_deg)
    vx = (cell.wind_mps * np.cos(wind) + cell.shear_mps_km * height_km * np.cos(shear)
          + rng.normal(0.0, max(core.turbulence_h_mps, 1e-9), size=count))
    vy = (cell.wind_mps * np.sin(wind) + cell.shear_mps_km * height_km * np.sin(shear)
          + rng.normal(0.0, max(core.turbulence_h_mps, 1e-9), size=count))
    vz = -fall + lift + rng.normal(0.0, max(core.turbulence_w_mps, 1e-9), size=count)
    return offsets, np.vstack([vx, vy, vz]), sizes


def cell_doppler(
    cell: Cell, band: Band, rng: np.random.Generator,
    scatterers: int = 6000, path_km: float = 0.0,
) -> tuple[list[CoreSample], dict[str, object]]:
    """Sample the whole cell: one Doppler frequency and weight per scatterer."""
    count = max(int(scatterers) // max(len(cell.cores), 1), 64)
    samples: list[CoreSample] = []
    powers: list[float] = []

    for core in cell.cores:
        offsets, velocity, sizes = _core_velocities(cell, core, count, rng)
        closing = cell.geometry.closing_vectors(offsets)
        freqs = np.asarray(band.bistatic_doppler_hz(np.sum(velocity * closing, axis=0)))
        weights = sizes**6.0
        total = float(weights.sum())
        weights = weights / total if total > 0 else np.full(count, 1.0 / count)
        centre, spread = moments(freqs, weights)
        # How far this core's note moves when the air through it lifts by 1 m/s.
        hz_per_mps = float(np.sum(weights * closing[2]) / band.wavelength_m)
        # The share of the return: reflectivity, times how much of the beam the
        # core actually fills.  A core off to the side of the volume is only
        # partly illuminated, and sounds like a second, quieter station.
        reach = cell.geometry.blob_sigma_m()[0] / 1000.0
        spill = abs(core.offset_km) / max(reach + core.size_km / 2.0, 0.2)
        illumination = float(np.exp(-0.5 * spill**2))
        powers.append(10.0 ** (reflectivity_dbz(core.rate_mm_h, cell.kind, cell.wet) / 10.0)
                      * illumination)
        samples.append(CoreSample(
            core=core, freqs=freqs, weights=weights, sizes=sizes,
            centre_hz=centre, spread_hz=spread, power=illumination,
            hz_per_mps=hz_per_mps,
        ))

    total_power = float(sum(powers))
    for sample, power in zip(samples, powers):
        share = power / total_power if total_power > 0 else 1.0 / len(samples)
        sample.weights = sample.weights * share
        sample.power = share

    freqs = np.concatenate([s.freqs for s in samples])
    weights = np.concatenate([s.weights for s in samples])
    sizes = np.concatenate([s.sizes for s in samples])
    shift, spread = moments(freqs, weights)
    geometry = cell.geometry
    azimuth = np.radians(cell.wind_azimuth_deg)
    wind_vector = cell.wind_mps * np.array([np.cos(azimuth), np.sin(azimuth), 0.0])
    closing_centre = geometry.closing_vectors(np.zeros((3, 1)))[:, 0]
    # As an equivalent one-way radial speed, so it compares with a fall speed.
    wind_along = float(np.dot(wind_vector, closing_centre) / 2.0)

    info: dict[str, object] = {
        "kind": "wet snow" if (cell.kind == "snow" and cell.wet) else cell.kind,
        "cell": cell.name,
        "character": cell.character,
        "rate_mm_h": cell.rate_mm_h,
        # The cores share the volume, so what the pair sees is the average of
        # their reflectivities, not the sum: four cores of 12 mm/h are still a
        # 12 mm/h cell, not one 6 dB louder.
        "dbz": (10.0 * float(np.log10(total_power / len(samples))) if total_power > 0
                else float("-inf")),
        "shift_hz": shift,
        "spread_hz": spread,
        "scatterers": int(freqs.size),
        "cores": [
            {"shift_hz": s.centre_hz, "spread_hz": s.spread_hz,
             "rate_mm_h": s.core.rate_mm_h, "updraft_mps": s.core.updraft_mps,
             "offset_km": s.core.offset_km,
             "level_db": 10.0 * float(np.log10(max(s.power, 1e-9)))}
            for s in samples
        ],
        "updraft_mps": float(np.sum([s.power * s.core.updraft_mps for s in samples])),
        "lift_gradient_mps_km": float(
            np.sum([s.power * abs(s.core.lift_gradient_mps_km) for s in samples])),
        "turbulence_mps": float(np.sum([s.power * s.core.turbulence_w_mps for s in samples])),
        "wind_mps": cell.wind_mps,
        "wind_azimuth_deg": cell.wind_azimuth_deg,
        "wind_along_mps": wind_along,
        "shear_mps_km": cell.shear_mps_km,
        "evolve_rate_hz": cell.evolve_rate_hz,
        "geometry": {
            "elevation_deg": geometry.elevation_deg,
            "far_elevation_deg": geometry.far_elevation_deg,
            "squint_deg": geometry.squint_deg,
            "height_km": geometry.height_km,
            "beamwidth_deg": geometry.beamwidth_deg,
            "depth_km": geometry.depth_km,
            "baseline_km": geometry.baseline_km,
            "bistatic_deg": geometry.bistatic_angle_deg,
            "sensitivity": geometry.sensitivity,
            "volume_km": tuple(round(v / 1000.0, 2) for v in geometry.blob_sigma_m()),
        },
        "attenuation_db": cell.attenuation_db(band, path_km),
    }
    if cell.kind == "snow":
        info["median_melted_mm"] = weighted_median(sizes, weights)
    else:
        info["median_drop_mm"] = weighted_median(sizes, weights)
    return samples, info


def evolution(
    cell: Cell, samples: list[CoreSample], frames: int, hop_s: float,
    rng: np.random.Generator, evolve: bool = True,
) -> list[Component]:
    """Turn the cores into channel components that change while you listen.

    A cell does not hold still for the thirteen seconds of a call: cores grow
    and decay, the air through them speeds up and slows down, the volume the
    beams share fills and empties.  Each core gets its own slow wander in
    level, in mean Doppler and in width, all at the cell's own pace -- fast for
    a convective core, barely moving for stratiform rain.
    """
    frames = max(int(frames), 1)
    rate = 1.0 / max(hop_s, 1e-6)
    components: list[Component] = []
    for sample in samples:
        core = sample.core
        if not evolve or frames < 4:
            gain = np.ones(frames)
            shift = np.zeros(frames)
            width = np.ones(frames)
        else:
            swing = np.clip(smooth_noise(frames, rate, core.breathe_rate_hz, rng), -2.5, 2.5)
            gain = np.power(10.0, core.breathe_db * (swing / 2.5 - 1.0) / 2.0 / 10.0)
            drift = np.clip(smooth_noise(frames, rate, core.wander_rate_hz, rng), -2.5, 2.5)
            shift = sample.hz_per_mps * core.wander_mps * drift / 2.5
            breath = np.clip(
                smooth_noise(frames, rate, core.breathe_rate_hz * 0.7, rng), -2.5, 2.5)
            width = np.clip(1.0 + core.width_swing * breath / 2.5, 0.2, 3.0)
        components.append(Component(
            freqs=sample.freqs, weights=sample.weights, centre_hz=sample.centre_hz,
            gain=gain, shift=shift, width=width,
        ))
    return components


def sounds_like(spread_hz: float, audible: float = 1.0) -> str:
    """One line on what a spread that wide actually sounds like."""
    if audible < 0.05:
        return "nothing a filter this narrow will let through"
    if spread_hz < 12:
        return "almost clean CW, just a flutter on it"
    if spread_hz < 35:
        return "a soft rasp, easy copy"
    if spread_hz < 100:
        return "hissy, the usual rain scatter note"
    if spread_hz < 250:
        return "rough and wide, hard going"
    return "a wideband hiss, barely a note left — aurora-like"
