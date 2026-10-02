"""One call from text to samples: keying, propagation, band conditions, levels.

The chain mirrors a station on the air.  The wanted signal is keyed, optionally
scattered off rain, snow or an auroral curtain, and attenuated by the weather it
went through; everything else on the band is generated separately; both go
through the same IF filter; the noise bus is scaled to hit the requested
signal-to-noise ratio in that bandwidth; and the sum passes a soft limiter the
way an AGC rounds off a static crash.

Each random part of the render draws from its own independent stream, spawned
from the seed, so turning one effect on does not reshuffle any of the others.
With no seed given the entropy comes from the OS, and the seed that was used is
reported so any band can be heard again.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .dsp import bandpass, db_to_amp, rms, soft_limit
from .morse import Timing, duration, parse, timeline, to_code
from .noise import NoiseSpec, build_noise
from .propagation import (REFERENCE_RATE_MM_H, AuroraSpec, Band, RainSpec, SnowSpec,
                          aurora_doppler, parse_band, rain_doppler, reflectivity_dbz,
                          snow_doppler)
from .scatter import (ScatterSpec, activity_gate, apply_channel, audible_fraction,
                      channel, doppler_spectrum, rician_weights, scintillate)
from .synth import ToneSpec, keyed_tone

#: Every random stream in a render, in a fixed order, so a given seed always
#: hands the same numbers to the same part of the chain.
STREAMS = ("signal", "weather", "scatter", "floor", "crashes", "qrm", "birdies")


def streams(seed: int | None) -> dict[str, np.random.Generator]:
    """Independent generators, one per part of the chain."""
    children = np.random.SeedSequence(seed).spawn(len(STREAMS))
    return {name: np.random.default_rng(child) for name, child in zip(STREAMS, children)}


@dataclass
class Config:
    """Every knob, flat, so the CLI can map onto it one for one."""

    # keying
    wpm: float = 23.0
    effective_wpm: float | None = None
    rise_ms: float = 5.0
    # our station's tone
    freq: float = 600.0
    drift_hz: float = 1.5
    drift_rate: float = 0.08
    qsb_db: float = 6.0
    qsb_rate: float = 0.25
    hum_depth: float = 0.0
    hum_hz: float = 50.0
    # propagation
    band: str = "10G"
    scatter: str = "none"           # none | rain | snow | aurora
    rician_db: float = -99.0        # direct-to-scattered ratio; -99 is pure scatter
    retune: bool = True             # tune the scattered signal back onto the note
    scintillation_db: float = 0.0
    scintillation_rate: float = 0.3
    doppler_shift_hz: float | None = None   # override the physics, audio Hz
    doppler_spread_hz: float | None = None
    scatterers: int = 6000
    elevation_deg: float = 8.0
    wind_mps: float | None = None        # None: the weather's own default
    wind_azimuth_deg: float | None = None
    turbulence_mps: float | None = None  # None: convective for rain, calm for snow
    path_km: float = 0.0
    weather_level: bool = True           # let reflectivity set the signal strength
    rain_rate: float = 12.0
    snow_rate: float = 4.0
    snow_wet: bool = False
    aurora_drift_mps: float = 600.0
    aurora_spread_mps: float = 200.0
    aurora_toward: bool = False
    aurora_activity: float = 0.55
    aurora_burst_s: float = 4.0
    # the band
    snr_db: float | None = 10.0
    bandwidth: float = 500.0
    tilt: float = 0.5
    crash_rate: float = 0.8
    crash_db: float = 22.0
    qrm_count: int = 1
    qrm_db: tuple[float, float] = (-6.0, 8.0)
    birdie_count: int = 0
    birdie_db: float = 4.0
    # output
    sample_rate: int = 44100
    pad: float = 0.6
    peak: float = 0.89
    limit: bool = True
    seed: int | None = None

    def tone_spec(self) -> ToneSpec:
        return ToneSpec(
            freq=self.freq,
            rise_ms=self.rise_ms,
            level=1.0,
            drift_hz=self.drift_hz,
            drift_rate=self.drift_rate,
            qsb_db=self.qsb_db,
            qsb_rate=self.qsb_rate,
            hum_depth=self.hum_depth,
            hum_hz=self.hum_hz,
        )

    def noise_spec(self) -> NoiseSpec:
        return NoiseSpec(
            bandwidth=self.bandwidth,
            snr_db=self.snr_db,
            tilt=self.tilt,
            crash_rate=self.crash_rate,
            crash_db=self.crash_db,
            qrm_count=self.qrm_count,
            qrm_db=tuple(self.qrm_db),
            birdie_count=self.birdie_count,
            birdie_db=self.birdie_db,
        )

    def scatter_spec(self) -> ScatterSpec:
        return ScatterSpec(
            mode=self.scatter,
            rician_db=self.rician_db,
            scintillation_db=self.scintillation_db,
            scintillation_rate=self.scintillation_rate,
            retune=self.retune,
        )

    def band_object(self) -> Band:
        return parse_band(self.band)


@dataclass
class Render:
    """Finished audio plus everything worth printing about it."""

    samples: np.ndarray
    sample_rate: int
    meta: dict[str, object] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.samples.size / self.sample_rate


def _scatterers(cfg: Config, band: Band, rng: np.random.Generator):
    """Sample the scattering volume for the configured mode."""
    mode = (cfg.scatter or "none").lower()
    weather = {}
    if cfg.wind_mps is not None:
        weather["wind_mps"] = cfg.wind_mps
    if cfg.turbulence_mps is not None:
        weather["turbulence_mps"] = cfg.turbulence_mps
    if mode == "rain":
        return rain_doppler(RainSpec(
            rate_mm_h=cfg.rain_rate, elevation_deg=cfg.elevation_deg,
            wind_azimuth_deg=cfg.wind_azimuth_deg, path_km=cfg.path_km,
            drops=cfg.scatterers, **weather), band, rng)
    if mode == "snow":
        return snow_doppler(SnowSpec(
            rate_mm_h=cfg.snow_rate, wet=cfg.snow_wet,
            elevation_deg=cfg.elevation_deg,
            wind_azimuth_deg=cfg.wind_azimuth_deg, path_km=cfg.path_km,
            flakes=cfg.scatterers, **weather), band, rng)
    if mode == "aurora":
        return aurora_doppler(AuroraSpec(
            drift_mps=cfg.aurora_drift_mps, drift_spread_mps=cfg.aurora_spread_mps,
            toward=cfg.aurora_toward, activity=cfg.aurora_activity,
            burst_s=cfg.aurora_burst_s, shift_hz=cfg.doppler_shift_hz,
            spread_hz=cfg.doppler_spread_hz, cells=cfg.scatterers), band, rng)
    raise ValueError(f"unknown scatter mode: {cfg.scatter!r}")


def _scattered_path(cfg: Config, env: np.ndarray, band: Band,
                    rngs: dict[str, np.random.Generator]):
    """Build the scattered copy of the signal.  Returns ``(audio, info)``."""
    samples, weights, info = _scatterers(cfg, band, rngs["weather"])
    grid, psd = doppler_spectrum(samples, weights)

    info["tuned_out_hz"] = 0.0
    if cfg.retune:
        # An operator tunes the return onto their own note; the spread stays.
        info["tuned_out_hz"] = info["shift_hz"]
        grid = grid - info["shift_hz"]

    info["audible_fraction"] = audible_fraction(
        grid, psd, cfg.freq, cfg.bandwidth, cfg.sample_rate)
    process = channel(env.size, cfg.sample_rate, grid, psd, cfg.freq, rngs["scatter"])

    if info["kind"] == "aurora":
        process = process * activity_gate(
            env.size, cfg.sample_rate, rngs["scatter"],
            cfg.aurora_activity, cfg.aurora_burst_s)
    if cfg.scintillation_db > 0:
        process = process * scintillate(
            env.size, cfg.sample_rate, rngs["scatter"],
            cfg.scintillation_db, cfg.scintillation_rate)

    audio = apply_channel(env, cfg.freq, cfg.sample_rate, process)
    return audio, info


def render(text: str, config: Config | None = None) -> Render:
    """Render ``text`` as Morse audio under ``config``'s band conditions."""
    cfg = config or Config()
    rngs = streams(cfg.seed)
    band = cfg.band_object()

    words, unknown = parse(text)
    timing = Timing(cfg.wpm, cfg.effective_wpm)
    elements = timeline(words, timing)
    keyed = duration(elements)
    n = max(1, int(np.ceil((keyed + 2 * cfg.pad) * cfg.sample_rate)))

    direct, env = keyed_tone(
        elements, cfg.sample_rate, cfg.tone_spec(), rngs["signal"], pad=cfg.pad, length=n
    )

    scatter_info: dict[str, object] = {}
    spec = cfg.scatter_spec()
    if spec.active:
        scattered, scatter_info = _scattered_path(cfg, env, band, rngs)
        direct_amp, scatter_amp = rician_weights(cfg.rician_db)
        loss = db_to_amp(-float(scatter_info.get("attenuation_db", 0.0)))
        signal = direct_amp * loss * direct + scatter_amp * scattered
    else:
        signal = direct

    noisy = cfg.snr_db is not None
    if noisy:
        signal = bandpass(signal, cfg.sample_rate, cfg.freq, cfg.bandwidth)

    key_down = env > 0.5
    key_up = env < 0.02
    down_power = float(np.mean(np.square(signal[key_down]))) if key_down.any() else 0.0

    # What the signal is worth: reflectivity sets how strong the return is
    # (12 mm/h of rain is the yardstick), and whatever the Doppler threw outside
    # the filter is power that never reaches the ear.
    effective_snr = cfg.snr_db
    if noisy and scatter_info:
        offset = 0.0
        if cfg.weather_level and np.isfinite(scatter_info.get("dbz", float("-inf"))):
            level = float(scatter_info["dbz"]) - reflectivity_dbz(REFERENCE_RATE_MM_H)
            scatter_info["level_offset_db"] = level
            offset += level
        fraction = float(scatter_info.get("audible_fraction", 1.0))
        loss = 10.0 * float(np.log10(max(fraction, 1e-9)))
        scatter_info["filter_loss_db"] = loss
        offset += loss
        effective_snr = float(cfg.snr_db) + offset

    noise_info: dict[str, object] = {}
    out = signal
    if noisy:
        bus, noise_info = build_noise(n, cfg.sample_rate, cfg.freq, cfg.noise_spec(), rngs)
        if down_power > 1e-18:
            # The floor has unit RMS, so this single gain sets S/N in the pass band.
            noise_gain = float(np.sqrt(down_power) / db_to_amp(float(effective_snr)))
        else:
            noise_gain = 0.25   # nothing of the signal survived: just the band, then
        out = signal + noise_gain * bus

    # Level: set the loud-but-not-crash level first, limit, then fill the file.
    reference = float(np.percentile(np.abs(out), 99.5)) if out.size else 0.0
    if reference > 1e-12:
        out = out * (0.7 / reference)
    if cfg.limit:
        out = soft_limit(out)
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 1e-12:
        out = out * (cfg.peak / peak)

    down_rms = rms(out[key_down]) if key_down.any() else 0.0
    up_rms = rms(out[key_up]) if key_up.any() else 0.0
    measured = None
    if up_rms > 1e-9 and down_rms > up_rms:
        measured = 20.0 * float(np.log10(np.sqrt(down_rms**2 - up_rms**2) / up_rms))

    meta: dict[str, object] = {
        "text": text.strip(),
        "code": to_code(words),
        "characters": sum(len(w) for w in words),
        "words": len(words),
        "unknown": unknown,
        "wpm": timing.wpm,
        "effective_wpm": timing.effective,
        "farnsworth": timing.is_farnsworth,
        "dit_ms": timing.unit * 1000.0,
        "char_gap_ms": timing.char_gap * 1000.0,
        "word_gap_ms": timing.word_gap * 1000.0,
        "keyed_seconds": keyed,
        "duration": n / cfg.sample_rate,
        "sample_rate": cfg.sample_rate,
        "tone_hz": cfg.freq,
        "band": band.label,
        "wavelength_mm": band.wavelength_m * 1000.0,
        "hz_per_mps": float(band.doppler_hz(1.0)),
        "scatter": scatter_info,
        "snr_db": cfg.snr_db,
        "effective_snr_db": effective_snr,
        "measured_snr_db": measured,
        "noise": noise_info,
        "seed": cfg.seed,
        "config": asdict(cfg),
    }
    return Render(out.astype(np.float64), cfg.sample_rate, meta)
