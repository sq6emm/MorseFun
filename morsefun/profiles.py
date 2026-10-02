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
}
