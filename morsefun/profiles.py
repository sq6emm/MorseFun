"""Band conditions worth keeping around, as named presets.

A profile sets the noise knobs; anything given on the command line still wins,
so ``--profile noisy --snr 12`` is a noisy band with a stronger signal.

Most knobs are not single numbers but :class:`Draw` ranges, resolved afresh for
every render from the seed: a *typical* band is 6 to 14 dB of signal, not
always 10, and the next render is a different evening on the same band.  The
knobs that would change what the mode *is* -- the band, the path, the keying
speed of a QRSS profile -- are pinned.

The noise floor follows the band.  Lightning static and the 1/f tilt of
atmospheric noise are an HF and LF thing: a 2 m or 10 GHz receiver hears white
receiver noise and nothing else, so those profiles have no crashes and no tilt.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Draw:
    """A range to draw a knob from, once per render."""

    lo: float
    hi: float
    log: bool = False       # draw log-uniformly, for rates and the like
    integer: bool = False

    def pick(self, rng: np.random.Generator | None):
        if rng is None:
            return self.middle
        if self.integer:
            return int(rng.integers(int(self.lo), int(self.hi) + 1))
        if self.log:
            return float(np.exp(rng.uniform(np.log(self.lo), np.log(self.hi))))
        return float(rng.uniform(self.lo, self.hi))

    @property
    def middle(self):
        if self.integer:
            return int(round((self.lo + self.hi) / 2.0))
        if self.log:
            return float(np.sqrt(self.lo * self.hi))
        return float((self.lo + self.hi) / 2.0)

    def __str__(self) -> str:
        if self.lo < 0 or self.hi < 0:
            return f"{self.lo:g} to {self.hi:g}"     # "-11 to -5", not "-11–-5"
        return f"{self.lo:g}–{self.hi:g}"


#: What a band at a given frequency has for a noise floor.
HF_FLOOR = {"tilt": 0.5}
WHITE_FLOOR = {"tilt": 0.0, "crash_rate": 0.0}

PROFILES: dict[str, dict[str, object]] = {
    "clean": {
        "snr_db": None, "crash_rate": 0.0, "qrm_count": 0, "qsb_db": 0.0,
        "drift_hz": 0.0, "birdie_count": 0, "hum_depth": 0.0, "limit": False,
    },
    "quiet": {
        "snr_db": Draw(16.0, 24.0), "crash_rate": Draw(0.05, 0.3, log=True),
        "qrm_count": Draw(0, 1, integer=True), "qsb_db": Draw(1.0, 4.0),
        "drift_hz": Draw(0.2, 0.8), "birdie_count": 0,
    },
    "typical": {
        "snr_db": Draw(6.0, 14.0), "crash_rate": Draw(0.3, 1.5, log=True),
        "qrm_count": Draw(0, 2, integer=True), "qsb_db": Draw(3.0, 9.0),
        "drift_hz": Draw(0.5, 2.5), "birdie_count": 0, "qrm_style": "mixed",
    },
    "noisy": {
        "snr_db": Draw(0.0, 5.0), "crash_rate": Draw(1.5, 4.0, log=True),
        "qrm_count": Draw(1, 3, integer=True), "qsb_db": Draw(8.0, 15.0),
        "drift_hz": Draw(2.0, 4.0), "birdie_count": Draw(0, 2, integer=True),
        "qrm_db": (-8.0, 4.0), "qrm_style": "mixed",
    },
    "contest": {
        "snr_db": Draw(5.0, 11.0), "crash_rate": Draw(0.3, 1.0, log=True),
        "qrm_count": Draw(4, 7, integer=True), "qsb_db": Draw(2.0, 6.0),
        "drift_hz": Draw(0.5, 2.0), "birdie_count": 1, "bandwidth": 700.0,
        "qrm_db": (-4.0, 10.0), "qrm_wpm": (26.0, 40.0), "qrm_style": "contest",
    },
    "thunderstorm": {
        "snr_db": Draw(3.0, 9.0), "crash_rate": Draw(4.0, 9.0), "crash_db": 26.0,
        "qrm_count": 0, "qsb_db": Draw(5.0, 10.0), "drift_hz": 1.0,
    },
    "rain-scatter": {
        # Nothing about the cloud is pinned: every render is a different front,
        # which is the whole point of the mode.
        "scatter": "rain", "band": "10G", "snr_db": Draw(7.0, 13.0),
        "qrm_count": Draw(0, 2, integer=True), "qsb_db": Draw(1.0, 3.0),
        "drift_hz": Draw(0.5, 2.0), "path_km": Draw(2.0, 12.0), **WHITE_FLOOR,
    },
    "light-rain": {
        # A long, symmetric path on a quiet day: the bisector points straight up
        # and there is almost nothing moving along it.
        "scatter": "rain", "band": "10G", "cell_character": Draw(0.03, 0.18),
        # Layered rain is well down on the 12 mm/h yardstick, so this only
        # works at all between two strong stations.
        "elevation_deg": Draw(1.5, 4.0), "squint_deg": Draw(0.0, 5.0),
        "wind_mps": Draw(3.0, 10.0), "snr_db": Draw(20.0, 28.0),
        "qrm_count": 0, "qsb_db": Draw(0.5, 2.0), "drift_hz": Draw(0.3, 1.2),
        "path_km": Draw(2.0, 6.0), **WHITE_FLOOR,
    },
    "heavy-rain": {
        "scatter": "rain", "band": "10G", "rain_rate": Draw(30.0, 70.0, log=True),
        "snr_db": Draw(7.0, 13.0), "qrm_count": 0, "qsb_db": Draw(1.0, 3.0),
        "drift_hz": Draw(0.5, 2.0), "turbulence_mps": Draw(2.5, 6.0),
        "path_km": Draw(4.0, 12.0), **WHITE_FLOOR,
    },
    "storm-front": {
        "scatter": "rain", "band": "10G", "cell_character": Draw(0.88, 1.0),
        "cores": Draw(3, 4, integer=True), "elevation_deg": Draw(8.0, 22.0),
        "snr_db": Draw(5.0, 11.0), "qrm_count": Draw(0, 1, integer=True),
        "qsb_db": Draw(1.0, 3.0), "drift_hz": Draw(0.5, 2.0),
        "path_km": Draw(3.0, 8.0), **WHITE_FLOOR,
    },
    "dry-snow": {
        "scatter": "snow", "band": "10G", "snow_rate": Draw(0.5, 2.0, log=True),
        "snr_db": Draw(7.0, 13.0), "qrm_count": 0, "qsb_db": Draw(0.5, 2.0),
        "drift_hz": Draw(0.5, 2.0), "scintillation_db": Draw(3.0, 8.0), **WHITE_FLOOR,
    },
    "wet-snow": {
        "scatter": "snow", "snow_wet": True, "band": "10G",
        "snow_rate": Draw(0.8, 3.0, log=True), "snr_db": Draw(7.0, 13.0),
        "qrm_count": 0, "qsb_db": Draw(0.5, 2.0), "drift_hz": Draw(0.5, 2.0),
        "scintillation_db": Draw(2.0, 6.0), **WHITE_FLOOR,
    },
    # QRSS: a dit of three seconds, read off a waterfall.  Nothing here is
    # listened to by ear, so the signal is allowed to sit below the noise: what
    # matters is that it is narrow, and that the path keeps it narrow.
    "lf-cw": {
        # 2200 m at eight words a minute: slow enough to read by ear, under a
        # noise floor made mostly of lightning.
        "scatter": "iono", "band": "137.5k", "wpm": 8.0, "rise_ms": 20.0,
        "snr_db": Draw(1.0, 6.0), "bandwidth": 250.0,
        "crash_rate": Draw(3.0, 8.0), "crash_db": 28.0,
        "tilt": 1.0, "qrm_count": 0, "qsb_db": 0.0, "drift_hz": 0.1,
        "drift_rate": 0.01, "hum_depth": 0.06, "birdie_count": 1, "birdie_db": 2.0,
    },
    "40m-dx": {
        # A night-time HF path: two or three modes arriving at once, each a
        # Rayleigh process a few tenths of a Hz wide, so it flutters and fades
        # every second or two without any fading model.
        "scatter": "iono", "band": "7.03M", "wpm": 20.0,
        "iono_modes": Draw(2, 3, integer=True), "snr_db": Draw(3.0, 10.0),
        "crash_rate": Draw(0.8, 2.5, log=True), "crash_db": 22.0,
        "qrm_count": Draw(1, 3, integer=True), "qsb_db": 0.0, "drift_hz": 0.5,
        "birdie_count": 0, "qrm_style": "mixed",
    },
    "contest-40m": {
        # Saturday night of a big one on 40 m: the band is wall to wall, six to
        # ten stations inside one filter, serials and zones at 30 wpm, a
        # pile-up sitting right on your frequency, and the skywave flutter on
        # all of it.
        "scatter": "iono", "band": "7.02M", "wpm": Draw(26.0, 34.0),
        "snr_db": Draw(6.0, 14.0), "bandwidth": 500.0,
        "crash_rate": Draw(0.5, 2.0, log=True), "crash_db": 22.0,
        "qrm_count": Draw(6, 10, integer=True), "qrm_db": (-10.0, 10.0),
        "qrm_wpm": (26.0, 40.0), "qrm_style": "contest",
        "qsb_db": 0.0, "drift_hz": 0.3, "birdie_count": Draw(0, 1, integer=True),
    },
    "contest-20m": {
        # The same weekend by day on 20 m: less lightning, a quieter floor,
        # the same wall of stations.
        "scatter": "iono", "band": "14.03M", "wpm": Draw(28.0, 36.0),
        "snr_db": Draw(8.0, 16.0), "bandwidth": 500.0,
        "crash_rate": Draw(0.1, 0.5, log=True), "crash_db": 18.0, "tilt": 0.3,
        "qrm_count": Draw(5, 9, integer=True), "qrm_db": (-10.0, 10.0),
        "qrm_wpm": (28.0, 42.0), "qrm_style": "contest",
        "qsb_db": 0.0, "drift_hz": 0.3, "birdie_count": 0,
    },
    "tropo-2m": {
        # Line of sight and a bit beyond: nothing much happens to the signal
        # except that it comes and goes.
        "scatter": "none", "band": "144M", "wpm": 18.0, "snr_db": Draw(5.0, 12.0),
        "qrm_count": Draw(0, 1, integer=True), "qsb_db": Draw(3.0, 8.0),
        "qsb_rate": 0.08, "drift_hz": 0.5, **WHITE_FLOOR,
    },
    "tropo-10g": {
        # A microwave tropo path: steady, but scintillating a few times a second,
        # and the rigs up there wander.
        "scatter": "none", "band": "10G", "wpm": 18.0, "snr_db": Draw(6.0, 14.0),
        "qrm_count": 0, "qsb_db": Draw(4.0, 9.0), "qsb_rate": 0.6,
        "drift_hz": Draw(1.5, 4.0), "drift_rate": 0.15, **WHITE_FLOOR,
    },
    "air-scatter": {
        # An airliner crossing the path: the note slides through the filter and
        # is gone again in half a minute.
        "scatter": "aircraft", "band": "10G", "wpm": 18.0, "snr_db": Draw(3.0, 9.0),
        "qrm_count": 0, "qsb_db": 0.0, "drift_hz": 1.0, **WHITE_FLOOR,
    },
    "eme-10g": {
        "scatter": "moon", "band": "10G", "wpm": 12.0, "snr_db": Draw(0.0, 4.0),
        "bandwidth": 500.0, "qrm_count": 0, "qsb_db": 0.0,
        "drift_hz": 2.0, **WHITE_FLOOR,
    },
    "lf-qrss": {
        "scatter": "iono", "band": "137.5k", "wpm": 0.4, "rise_ms": 200.0,
        "sample_rate": 8000, "snr_db": Draw(-15.0, -9.0), "bandwidth": 200.0,
        "crash_rate": Draw(3.0, 8.0), "crash_db": 28.0, "tilt": 1.0, "qrm_count": 0,
        "qsb_db": 0.0, "drift_hz": 0.02, "drift_rate": 0.002,
        "hum_depth": 0.06, "birdie_count": 1, "birdie_db": 2.0,
    },
    "mf-qrss": {
        "scatter": "iono", "band": "474k", "wpm": 0.4, "rise_ms": 200.0,
        "sample_rate": 8000, "snr_db": Draw(-13.0, -7.0), "bandwidth": 200.0,
        "crash_rate": Draw(2.0, 5.0), "crash_db": 26.0, "tilt": 0.8, "qrm_count": 0,
        "qsb_db": 0.0, "drift_hz": 0.05, "drift_rate": 0.002,
        "hum_depth": 0.03, "birdie_count": 1, "birdie_db": 2.0,
    },
    "30m-qrss": {
        "scatter": "iono", "band": "10.14M", "wpm": 0.4, "rise_ms": 200.0,
        "sample_rate": 8000, "snr_db": Draw(-11.0, -5.0), "bandwidth": 300.0,
        "crash_rate": Draw(0.3, 1.5, log=True), "crash_db": 20.0, "qrm_count": 1,
        "qsb_db": 0.0, "drift_hz": 0.3, "drift_rate": 0.003, "birdie_count": 1,
    },
    "eme-qrss": {
        "scatter": "moon", "band": "144M", "wpm": 0.4, "rise_ms": 200.0,
        "sample_rate": 8000, "snr_db": Draw(-9.0, -3.0), "bandwidth": 300.0,
        "qrm_count": 0, "qsb_db": 0.0, "drift_hz": 0.05, "drift_rate": 0.002,
        **WHITE_FLOOR,
    },
    "eme": {
        "scatter": "moon", "band": "144M", "wpm": 12.0, "snr_db": Draw(1.0, 6.0),
        "bandwidth": 300.0, "qrm_count": 0, "qsb_db": 0.0, "drift_hz": 1.0,
        **WHITE_FLOOR,
    },
    "aurora": {
        "scatter": "aurora", "band": "144M", "snr_db": Draw(9.0, 15.0),
        "qrm_count": Draw(0, 1, integer=True), "qsb_db": 0.0, "drift_hz": 0.0,
        "scintillation_db": 3.0, **WHITE_FLOOR,
    },
    "worn-rig": {
        "snr_db": Draw(11.0, 17.0), "crash_rate": Draw(0.2, 0.8, log=True),
        "qrm_count": 0, "qsb_db": 2.0, "drift_hz": Draw(4.0, 9.0), "drift_rate": 0.2,
        "hum_depth": Draw(0.08, 0.16), "birdie_count": 1,
    },
}

DEFAULT_PROFILE = "typical"


def resolve(name: str, rng: np.random.Generator | None = None) -> dict[str, object]:
    """A profile with every :class:`Draw` resolved: drawn from ``rng``, or the
    middle of each range when there is none (for a form's placeholders)."""
    return {field: value.pick(rng) if isinstance(value, Draw) else value
            for field, value in PROFILES[name].items()}


#: Which band each profile belongs to, and in what order to offer them: a front
#: end wants to ask for a band first and then for what the signal did to get
#: there, because that is how an operator thinks about it.  Every profile is in
#: exactly one group.
GROUPS: dict[str, dict[str, object]] = {
    "LF / MF": {
        "about": "2200 m and 630 m: a stable path under a floor of lightning, "
                 "so the trick is to be narrow rather than loud",
        "profiles": ("lf-qrss", "mf-qrss", "lf-cw"),
    },
    "HF": {
        "about": "the ionosphere arriving by more than one path at once, each "
                 "a Rayleigh flutter a few tenths of a Hz wide: that is where "
                 "the fading comes from",
        "profiles": ("40m-dx", "contest-40m", "contest-20m", "30m-qrss"),
    },
    "VHF / UHF": {
        "about": "line of sight, and the three ways past it: tropo, an auroral "
                 "curtain, and the Moon",
        "profiles": ("tropo-2m", "aurora", "eme", "eme-qrss"),
    },
    "Microwave": {
        "about": "10 GHz, where the weather is the propagation: rain, snow, "
                 "aeroplanes and the Moon",
        "profiles": ("tropo-10g", "rain-scatter", "light-rain", "heavy-rain",
                     "storm-front", "dry-snow", "wet-snow", "air-scatter",
                     "eme-10g"),
    },
    "Any band": {
        "about": "band conditions on their own, with no propagation model "
                 "behind them",
        "profiles": ("typical", "quiet", "noisy", "contest", "thunderstorm",
                     "worn-rig", "clean"),
    },
}


def group_of(name: str) -> str:
    """Which band group a profile belongs to."""
    for group, detail in GROUPS.items():
        if name in detail["profiles"]:
            return group
    return "Any band"


DESCRIPTIONS: dict[str, str] = {
    "clean": "bare tone, no band at all",
    "quiet": "good conditions, strong signal, the odd crash",
    "typical": "S/N 6 to 14 dB, slow fading, a neighbour or two in the pass band",
    "noisy": "weak signal, deep QSB, crashes and other stations",
    "contest": "a crowded band: four to seven stations and a carrier in a 700 Hz filter",
    "thunderstorm": "heavy static, crashes several times a second",
    "worn-rig": "clean band, drifting VFO and mains hum on the carrier",
    "rain-scatter": "10 GHz off a rain cell: a different front every time",
    "light-rain": "10 GHz off layered rain on a long path: almost clean CW",
    "storm-front": "10 GHz into a storm: several cores, lift, shear, aurora-like",
    "heavy-rain": "10 GHz off a downpour: 30 to 70 mm/h, loud, wide and attenuated",
    "dry-snow": "10 GHz off dry snow: narrow, wind-shifted, a few dB down",
    "wet-snow": "10 GHz off the melting layer: the bright band, stronger than rain",
    "aurora": "aurora on 2 m, where it works: hoarse, bursty, shifted down",
    "lf-cw": "2200 m at 8 wpm: readable by ear, buried in lightning",
    "40m-dx": "40 m at night: two or three modes, fluttering and fading every second or two",
    "contest-40m": "40 m on a contest night: six to ten stations in the filter, a pile-up on you",
    "contest-20m": "20 m contest by day: quieter floor, the same wall of stations at 30 wpm",
    "tropo-2m": "2 m tropo: steady, with a slow fade on it",
    "tropo-10g": "10 GHz tropo: scintillating, and the rig wanders",
    "air-scatter": "10 GHz off an airliner: a note that slides and is gone",
    "eme-10g": "10 GHz moonbounce: 30 kHz of Doppler tracked out",
    "lf-qrss": "2200 m QRSS3: a trace like a hair, under heavy static",
    "mf-qrss": "630 m QRSS3: still razor thin, a little more layer motion",
    "30m-qrss": "30 m QRSS3: the knights' band, fuzzy and wandering",
    "eme-qrss": "2 m EME QRSS3: the echo 2.5 s late, libration and Faraday",
    "eme": "2 m moonbounce at 12 wpm: hollow, fluttery, 2.5 s behind you",
}
