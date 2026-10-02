"""Band conditions worth keeping around, as named presets.

A profile sets the noise knobs; anything given on the command line still wins,
so ``--profile noisy --snr 12`` is a noisy band with a stronger signal.
"""

from __future__ import annotations

PROFILES: dict[str, dict[str, object]] = {
    "clean": {
        "snr_db": None, "crash_rate": 0.0, "qrm_count": 0, "qsb_db": 0.0,
        "drift_hz": 0.0, "birdie_count": 0, "hum_depth": 0.0, "limit": False,
    },
    "quiet": {
        "snr_db": 20.0, "crash_rate": 0.15, "qrm_count": 0, "qsb_db": 3.0,
        "drift_hz": 0.5, "birdie_count": 0,
    },
    "typical": {
        "snr_db": 10.0, "crash_rate": 0.8, "qrm_count": 1, "qsb_db": 6.0,
        "drift_hz": 1.5, "birdie_count": 0,
    },
    "noisy": {
        "snr_db": 3.0, "crash_rate": 2.5, "qrm_count": 2, "qsb_db": 12.0,
        "drift_hz": 3.0, "birdie_count": 1, "qrm_db": (-8.0, 4.0),
    },
    "contest": {
        "snr_db": 8.0, "crash_rate": 0.6, "qrm_count": 4, "qsb_db": 4.0,
        "drift_hz": 1.5, "birdie_count": 1, "bandwidth": 700.0,
        "qrm_db": (-4.0, 10.0),
    },
    "thunderstorm": {
        "snr_db": 6.0, "crash_rate": 6.0, "crash_db": 26.0, "qrm_count": 0,
        "qsb_db": 8.0, "drift_hz": 1.0,
    },
    "rain-scatter": {
        # Nothing about the cloud is pinned: every render is a different front,
        # which is the whole point of the mode.
        "scatter": "rain", "band": "10G", "snr_db": 10.0,
        "crash_rate": 0.1, "qrm_count": 1, "qsb_db": 2.0, "drift_hz": 1.0,
        "path_km": 6.0,
    },
    "light-rain": {
        # A long, symmetric path on a quiet day: the bisector points straight up
        # and there is almost nothing moving along it.
        "scatter": "rain", "band": "10G", "cell_character": 0.10,
        # Layered rain is 14 dB down on the 12 mm/h yardstick, so this only
        # works at all between two strong stations.
        "elevation_deg": 2.5, "squint_deg": 2.0, "wind_mps": 6.0,
        "snr_db": 24.0, "crash_rate": 0.05,
        "qrm_count": 0, "qsb_db": 1.0, "drift_hz": 0.8, "path_km": 4.0,
    },
    "heavy-rain": {
        "scatter": "rain", "band": "10G", "rain_rate": 45.0, "snr_db": 10.0,
        "crash_rate": 1.2, "qrm_count": 0, "qsb_db": 2.0, "drift_hz": 1.0,
        "turbulence_mps": 4.0, "path_km": 8.0,
    },
    "storm-front": {
        "scatter": "rain", "band": "10G", "cell_character": 0.95, "cores": 4,
        "elevation_deg": 14.0, "snr_db": 8.0, "crash_rate": 3.0, "crash_db": 24.0,
        "qrm_count": 1, "qsb_db": 2.0, "drift_hz": 1.0, "path_km": 5.0,
    },
    "dry-snow": {
        "scatter": "snow", "band": "10G", "snow_rate": 4.0, "snr_db": 10.0,
        "crash_rate": 0.05, "qrm_count": 0, "qsb_db": 1.0, "drift_hz": 1.0,
        "scintillation_db": 6.0,
    },
    "wet-snow": {
        "scatter": "snow", "snow_wet": True, "band": "10G", "snow_rate": 5.0,
        "snr_db": 10.0, "crash_rate": 0.05, "qrm_count": 0, "qsb_db": 1.0,
        "drift_hz": 1.0, "scintillation_db": 4.0,
    },
    # QRSS: a dit of three seconds, read off a waterfall.  Nothing here is
    # listened to by ear, so the signal is allowed to sit below the noise: what
    # matters is that it is narrow, and that the path keeps it narrow.
    "lf-cw": {
        # 2200 m at eight words a minute: slow enough to read by ear, under a
        # noise floor made mostly of lightning.
        "scatter": "iono", "band": "137.5k", "wpm": 8.0, "rise_ms": 20.0,
        "snr_db": 3.0, "bandwidth": 250.0, "crash_rate": 5.0, "crash_db": 28.0,
        "tilt": 1.0, "qrm_count": 0, "qsb_db": 0.0, "drift_hz": 0.1,
        "drift_rate": 0.01, "hum_depth": 0.06, "birdie_count": 1, "birdie_db": 2.0,
    },
    "40m-dx": {
        # A night-time HF path: two or three hops arriving at once, so it fades
        # on its own without any fading model.
        "scatter": "iono", "band": "7.03M", "wpm": 20.0, "iono_modes": 3,
        "snr_db": 6.0, "crash_rate": 1.5, "crash_db": 22.0, "qrm_count": 2,
        "qsb_db": 0.0, "drift_hz": 0.5, "birdie_count": 0,
    },
    "tropo-2m": {
        # Line of sight and a bit beyond: nothing much happens to the signal
        # except that it comes and goes.
        "scatter": "none", "band": "144M", "wpm": 18.0, "snr_db": 8.0,
        "crash_rate": 0.2, "qrm_count": 1, "qsb_db": 5.0, "qsb_rate": 0.08,
        "drift_hz": 0.5,
    },
    "tropo-10g": {
        # A microwave tropo path: steady, but scintillating a few times a second,
        # and the rigs up there wander.
        "scatter": "none", "band": "10G", "wpm": 18.0, "snr_db": 10.0,
        "crash_rate": 0.05, "qrm_count": 0, "qsb_db": 7.0, "qsb_rate": 0.6,
        "drift_hz": 3.0, "drift_rate": 0.15,
    },
    "air-scatter": {
        # An airliner crossing the path: the note slides through the filter and
        # is gone again in half a minute.
        "scatter": "aircraft", "band": "10G", "wpm": 18.0, "snr_db": 6.0,
        "crash_rate": 0.05, "qrm_count": 0, "qsb_db": 0.0, "drift_hz": 1.0,
    },
    "eme-10g": {
        "scatter": "moon", "band": "10G", "wpm": 12.0, "snr_db": 2.0,
        "bandwidth": 500.0, "crash_rate": 0.05, "qrm_count": 0, "qsb_db": 0.0,
        "drift_hz": 2.0,
    },
    "lf-qrss": {
        "scatter": "iono", "band": "137.5k", "wpm": 0.4, "rise_ms": 200.0,
        "sample_rate": 8000, "snr_db": -12.0, "bandwidth": 200.0,
        "crash_rate": 5.0, "crash_db": 28.0, "tilt": 1.0, "qrm_count": 0,
        "qsb_db": 0.0, "drift_hz": 0.02, "drift_rate": 0.002,
        "hum_depth": 0.06, "birdie_count": 1, "birdie_db": 2.0,
    },
    "mf-qrss": {
        "scatter": "iono", "band": "474k", "wpm": 0.4, "rise_ms": 200.0,
        "sample_rate": 8000, "snr_db": -10.0, "bandwidth": 200.0,
        "crash_rate": 3.0, "crash_db": 26.0, "tilt": 0.8, "qrm_count": 0,
        "qsb_db": 0.0, "drift_hz": 0.05, "drift_rate": 0.002,
        "hum_depth": 0.03, "birdie_count": 1, "birdie_db": 2.0,
    },
    "30m-qrss": {
        "scatter": "iono", "band": "10.14M", "wpm": 0.4, "rise_ms": 200.0,
        "sample_rate": 8000, "snr_db": -8.0, "bandwidth": 300.0,
        "crash_rate": 0.8, "crash_db": 20.0, "qrm_count": 1, "qsb_db": 0.0,
        "drift_hz": 0.3, "drift_rate": 0.003, "birdie_count": 1,
    },
    "eme-qrss": {
        "scatter": "moon", "band": "144M", "wpm": 0.4, "rise_ms": 200.0,
        "sample_rate": 8000, "snr_db": -6.0, "bandwidth": 300.0,
        "crash_rate": 0.2, "qrm_count": 0, "qsb_db": 0.0, "drift_hz": 0.05,
        "drift_rate": 0.002,
    },
    "eme": {
        "scatter": "moon", "band": "144M", "wpm": 12.0, "snr_db": 3.0,
        "bandwidth": 300.0, "crash_rate": 0.3, "qrm_count": 0, "qsb_db": 0.0,
        "drift_hz": 1.0,
    },
    "aurora": {
        "scatter": "aurora", "band": "144M", "snr_db": 12.0, "crash_rate": 0.3,
        "qrm_count": 1, "qsb_db": 0.0, "drift_hz": 0.0, "scintillation_db": 3.0,
    },
    "worn-rig": {
        "snr_db": 14.0, "crash_rate": 0.4, "qrm_count": 0, "qsb_db": 2.0,
        "drift_hz": 6.0, "drift_rate": 0.2, "hum_depth": 0.12, "birdie_count": 1,
    },
}

DEFAULT_PROFILE = "typical"

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
        "about": "the ionosphere arriving by more than one path at once, which "
                 "is where fading comes from",
        "profiles": ("40m-dx", "30m-qrss"),
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
    "typical": "S/N 10 dB, slow fading, one neighbour in the pass band",
    "noisy": "weak signal, deep QSB, crashes and two other stations",
    "contest": "a crowded band: four stations and a carrier in a 700 Hz filter",
    "thunderstorm": "heavy static, crashes several times a second",
    "worn-rig": "clean band, drifting VFO and mains hum on the carrier",
    "rain-scatter": "10 GHz off a rain cell: a different front every time",
    "light-rain": "10 GHz off layered rain on a long path: almost clean CW",
    "storm-front": "10 GHz into a storm: four cores, lift, shear, aurora-like",
    "heavy-rain": "10 GHz off a downpour: 45 mm/h, loud, wide and attenuated",
    "dry-snow": "10 GHz off dry snow: narrow, wind-shifted and very weak",
    "wet-snow": "10 GHz off the melting layer: the bright band, much stronger",
    "aurora": "aurora on 2 m, where it works: hoarse, bursty, shifted down",
    "lf-cw": "2200 m at 8 wpm: readable by ear, buried in lightning",
    "40m-dx": "40 m at night: three hops beating against each other",
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
