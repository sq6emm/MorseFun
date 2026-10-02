"""One call from text to samples: keying, propagation, band conditions, levels.

The chain mirrors a station on the air.  The wanted signal is keyed, optionally
scattered off a rain cell, falling snow or an auroral curtain, and attenuated by
the weather it went through; everything else on the band is generated
separately; both go through the same IF filter; the noise bus is scaled to hit
the requested signal-to-noise ratio in that bandwidth; and the sum passes a soft
limiter the way an AGC rounds off a static crash.

Each random part of the render draws from its own independent stream, spawned
from the seed, so turning one effect on does not reshuffle any of the others.
With no seed given the entropy comes from the OS, and the seed that was used is
reported so any band -- and any cloud -- can be heard again.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .cell import (Cell, cell_doppler, draw_cell, evolution, parse_character,
                   sounds_like)
from .dsp import bandpass, db_to_amp, fast_length, rms, soft_limit
from .moon import draw_moon, faraday_fade, moon_doppler
from .morse import Timing, duration, parse, timeline, to_code
from .noise import NoiseSpec, build_noise
from .propagation import (REFERENCE_RATE_MM_H, AuroraSpec, Band, aurora_doppler,
                          parse_band, reflectivity_dbz)
from .scatter import (Component, EvolvingSpectrum, ScatterSpec, activity_gate,
                      apply_channel, audible_fraction, block_size, channel,
                      coherent_channel, doppler_spectrum, evolving_channel,
                      frame_count, rician_weights, scintillate)
from .skywave import draw_iono, iono_carriers
from .synth import ToneSpec, keyed_tone

#: Every random stream in a render, in a fixed order, so a given seed always
#: hands the same numbers to the same part of the chain.
STREAMS = ("signal", "weather", "scatter", "floor", "crashes", "qrm", "birdies")

#: The modes that are a volume of weather with cores in it.
WEATHER_MODES = ("rain", "snow")

#: What people call these paths, and what this module calls them.
MODE_ALIASES = {"eme": "moon", "lunar": "moon", "skywave": "iono",
                "ionosphere": "iono", "iono": "iono", "moon": "moon"}

MODES = ("none", "rain", "snow", "aurora", "iono", "moon")

#: Below three words a minute nobody is listening by ear any more: the message
#: is read off a waterfall, in a bin about 1/dit wide.  That is QRSS.
QRSS_DIT_S = 0.4

#: A render has to fit in memory and in somebody's afternoon.
MAX_SAMPLES = 40_000_000


def mode_name(scatter: str | None) -> str:
    """The canonical name of a propagation mode, or ``none``."""
    name = str(scatter or "none").strip().lower()
    if name in ("", "none"):
        return "none"
    return MODE_ALIASES.get(name, name)


def qrss_label(dit_s: float) -> str:
    """``QRSS3`` for a three-second dit, the way everybody writes it."""
    return f"QRSS{dit_s:g}" if dit_s >= 1.0 else f"dit {dit_s * 1000:.0f} ms"


def apply_qrss(cfg: Config, dit_s: float, keep_rise: bool = False,
               keep_rate: bool = False) -> Config:
    """Set a keying speed from a dit length in seconds, and keep it narrow.

    Two things come with it unless they were asked for by hand.  The envelope
    has to rise slowly -- a three-second dit with a five-millisecond edge has
    sidebands two hundred Hz out, which is absurd when the whole point is a
    trace a tenth of a Hz wide -- and the sample rate can come down, because
    nothing above a couple of kHz is wanted and the file would otherwise be
    enormous.
    """
    if dit_s <= 0:
        raise ValueError("a dit has to last longer than that")
    cfg.wpm = 1.2 / float(dit_s)
    if not keep_rise:
        cfg.rise_ms = float(min(max(dit_s * 1000.0 / 15.0, 5.0), 400.0))
    if not keep_rate and dit_s >= QRSS_DIT_S:
        cfg.sample_rate = 8000
    return cfg


def streams(seed: int | None) -> dict[str, np.random.Generator]:
    """Independent generators, one per part of the chain."""
    children = np.random.SeedSequence(seed).spawn(len(STREAMS))
    return {name: np.random.default_rng(child) for name, child in zip(STREAMS, children)}


@dataclass
class Config:
    """Every knob, flat, so the CLI can map onto it one for one.

    Most of the weather is ``None`` by default, which does not mean *off*: it
    means *drawn*.  Give a number and that number is kept; leave it alone and
    every render sees a different cloud.
    """

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
    scintillation_db: float | None = None   # None: whatever the cell deserves
    scintillation_rate: float | None = None
    doppler_shift_hz: float | None = None   # override the physics, audio Hz
    doppler_spread_hz: float | None = None
    scatterers: int = 6000
    weather_level: bool = True           # let reflectivity set the signal strength
    path_km: float = 0.0                 # weather along the path, for attenuation
    # the cell, all drawn unless pinned
    cell_character: float | str | None = None   # 0 stratiform .. 1 deep convective
    cores: int | None = None             # scattering centres in the volume
    rain_rate: float | None = None       # mm/h
    snow_rate: float | None = None       # mm/h water equivalent
    snow_wet: bool = False
    updraft_mps: float | None = None     # bulk vertical motion in the cores
    turbulence_mps: float | None = None  # velocity spread inside them
    shear_mps_km: float | None = None    # wind change through the volume
    wind_mps: float | None = None
    wind_azimuth_deg: float | None = None
    # the geometry both ends see it with
    elevation_deg: float | None = None
    squint_deg: float | None = None       # cell off the line between the stations
    beamwidth_deg: float | None = None
    height_km: float | None = None
    depth_km: float | None = None
    evolve: bool = True                   # let the cell change while you listen
    evolve_rate_hz: float | None = None
    qrm_scatter: bool = True              # the neighbours are on the same cell
    # EME: the Moon is 2.5 seconds away and never holds still
    moon_distance_km: float | None = None
    libration_deg_day: float | None = None    # apparent rotation, 0.2 .. 8
    moon_range_rate_mps: float | None = None  # own Doppler, up to ±465 m/s
    moon_accel_mps2: float | None = None      # how fast that changes
    moon_scatter_law: float | None = None     # cos^n across the disc
    faraday_db: float | None = None           # VHF polarisation fading
    doppler_track: bool = True                # follow the Doppler, as rigs do
    # a low band: the skywave path, seen through a milliHertz filter
    iono_modes: int | None = None             # hops or magneto-ionic components
    layer_rate_mps: float | None = None       # how fast the layer is moving
    layer_turbulence_mps: float | None = None
    takeoff_deg: float | None = None
    # aurora
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
            scintillation_db=self.scintillation_db or 0.0,
            scintillation_rate=self.scintillation_rate or 0.3,
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


def draw_weather(cfg: Config, mode: str, rng: np.random.Generator,
                 character: float | None = None, rate_mm_h: float | None = None) -> Cell:
    """Draw the cell this render listens to, keeping whatever was pinned."""
    if character is None:
        character = parse_character(cfg.cell_character)
    if rate_mm_h is None:
        rate_mm_h = cfg.rain_rate if mode == "rain" else cfg.snow_rate
    return draw_cell(
        rng, kind=mode,
        character=character,
        rate_mm_h=rate_mm_h,
        cores=cfg.cores,
        updraft_mps=cfg.updraft_mps,
        turbulence_mps=cfg.turbulence_mps,
        shear_mps_km=cfg.shear_mps_km,
        wind_mps=cfg.wind_mps,
        wind_azimuth_deg=cfg.wind_azimuth_deg,
        elevation_deg=cfg.elevation_deg,
        squint_deg=cfg.squint_deg,
        beamwidth_deg=cfg.beamwidth_deg,
        height_km=cfg.height_km,
        depth_km=cfg.depth_km,
        evolve_rate_hz=cfg.evolve_rate_hz,
        scintillation_db=cfg.scintillation_db,
        wet=cfg.snow_wet,
    )


def _weather_path(cfg: Config, env: np.ndarray, band: Band, mode: str,
                  rngs: dict[str, np.random.Generator]):
    """Scatter off a cell that has cores, a shape, and somewhere to be."""
    cell = draw_weather(cfg, mode, rngs["weather"])
    samples, info = cell_doppler(
        cell, band, rngs["weather"], scatterers=cfg.scatterers, path_km=cfg.path_km)

    # A narrow spectrum needs a long analysis block to resolve it, and can
    # afford one: a cell that narrow is a cell that changes slowly anyway.
    block = block_size(info["spread_hz"], cfg.sample_rate, env.size)
    hop = block // 2
    components = evolution(
        cell, samples, frame_count(env.size, block), hop / cfg.sample_rate,
        rngs["weather"], evolve=cfg.evolve)
    spectrum = EvolvingSpectrum(components, smooth_hz=max(
        float(info["spread_hz"]) / 12.0, 0.8 * cfg.sample_rate / max(block, 1)))

    # What is quoted is the spectrum averaged over the whole message, wander and
    # all, because that is what the ear integrates.
    shift, spread = spectrum.moments()
    info["still_spread_hz"] = info["spread_hz"]
    info["shift_hz"], info["spread_hz"] = shift, spread
    info["tuned_out_hz"] = 0.0
    if cfg.retune:
        info["tuned_out_hz"] = shift
        spectrum.retune(-shift)
    info["audible_fraction"] = audible_fraction(
        spectrum.grid, spectrum.mean_psd(), cfg.freq, cfg.bandwidth, cfg.sample_rate)
    info["evolving"] = bool(cfg.evolve)
    info["frame_ms"] = 1000.0 * hop / cfg.sample_rate
    info["sounds_like"] = sounds_like(spread, float(info["audible_fraction"]))

    process = evolving_channel(
        env.size, cfg.sample_rate, spectrum, cfg.freq, rngs["scatter"], block)

    depth = cell.scintillation_db if cfg.scintillation_db is None else cfg.scintillation_db
    rate = (cell.scintillation_rate_hz if cfg.scintillation_rate is None
            else cfg.scintillation_rate)
    info["scintillation_db"] = float(depth)
    if depth > 0:
        process = process * scintillate(
            env.size, cfg.sample_rate, rngs["scatter"], float(depth), float(rate))

    return apply_channel(env, cfg.freq, cfg.sample_rate, process), info, cell


def _aurora_path(cfg: Config, env: np.ndarray, band: Band,
                 rngs: dict[str, np.random.Generator]):
    """Scatter off an auroral curtain: one spectrum, and a gate that opens."""
    freqs, weights, info = aurora_doppler(AuroraSpec(
        drift_mps=cfg.aurora_drift_mps, drift_spread_mps=cfg.aurora_spread_mps,
        toward=cfg.aurora_toward, activity=cfg.aurora_activity,
        burst_s=cfg.aurora_burst_s, shift_hz=cfg.doppler_shift_hz,
        spread_hz=cfg.doppler_spread_hz, cells=cfg.scatterers), band, rngs["weather"])
    grid, psd = doppler_spectrum(freqs, weights)

    info["tuned_out_hz"] = 0.0
    if cfg.retune:
        info["tuned_out_hz"] = info["shift_hz"]
        grid = grid - info["shift_hz"]
    info["audible_fraction"] = audible_fraction(
        grid, psd, cfg.freq, cfg.bandwidth, cfg.sample_rate)
    info["sounds_like"] = sounds_like(
        float(info["spread_hz"]), float(info["audible_fraction"]))

    process = channel(env.size, cfg.sample_rate, grid, psd, cfg.freq, rngs["scatter"])
    process = process * activity_gate(
        env.size, cfg.sample_rate, rngs["scatter"], cfg.aurora_activity, cfg.aurora_burst_s)
    depth = 0.0 if cfg.scintillation_db is None else float(cfg.scintillation_db)
    info["scintillation_db"] = depth
    if depth > 0:
        process = process * scintillate(
            env.size, cfg.sample_rate, rngs["scatter"], depth,
            float(cfg.scintillation_rate or 0.3))
    return apply_channel(env, cfg.freq, cfg.sample_rate, process), info


def _narrow_block(spread_hz: float, sample_rate: int, size: int) -> int:
    """Analysis block for a path whose spectrum is a hair wide.

    A skywave or libration-minimum spectrum can be hundredths of a Hz across,
    so the usual couple of thousand samples would synthesise something a
    hundred times too wide.  These paths are allowed a block up to a million
    samples -- two minutes at 8 kHz -- which is fine, because nothing in them
    changes in two minutes either.
    """
    return block_size(max(float(spread_hz), 1e-3), sample_rate, size, hi=1 << 20)


def _iono_path(cfg: Config, env: np.ndarray, band: Band,
               rngs: dict[str, np.random.Generator]):
    """A low band: one or more coherent hops off a layer that will not hold still."""
    spec = draw_iono(rngs["weather"], band, modes=cfg.iono_modes,
                     height_rate_mps=cfg.layer_rate_mps,
                     turbulence_mps=cfg.layer_turbulence_mps,
                     elevation_deg=cfg.takeoff_deg)
    carriers, info = iono_carriers(spec, band)

    info["tuned_out_hz"] = 0.0
    if cfg.retune:
        # The operator sits on the trace, not on the nominal frequency.
        info["tuned_out_hz"] = float(info["shift_hz"])
        for carrier in carriers:
            carrier.shift_hz -= float(info["shift_hz"])
    info["audible_fraction"] = 1.0
    info["sounds_like"] = sounds_like(float(info["spread_hz"]),
                                      float(info["audible_fraction"]))
    process = coherent_channel(env.size, cfg.sample_rate, carriers, rngs["scatter"])
    depth = 0.0 if cfg.scintillation_db is None else float(cfg.scintillation_db)
    info["scintillation_db"] = depth
    if depth > 0:
        process = process * scintillate(
            env.size, cfg.sample_rate, rngs["scatter"], depth,
            float(cfg.scintillation_rate or 0.05))
    return apply_channel(env, cfg.freq, cfg.sample_rate, process), info


def _moon_path(cfg: Config, env: np.ndarray, band: Band, spec,
               rngs: dict[str, np.random.Generator]):
    """EME: the whole face of the Moon answering, 2.5 seconds late."""
    freqs, weights, info = moon_doppler(spec, band, rngs["weather"])
    block = _narrow_block(info["spread_hz"], cfg.sample_rate, env.size)
    hop = max(block // 2, 1)
    frames = frame_count(env.size, block)

    # Where the echo sits: the station's own Doppler, and the ramp as the Earth
    # turns under it.  A rig that tracks takes both out; a dial takes out the
    # offset and leaves the ramp to slope the trace across the screen.
    middle = 0.5 * (frames - 1) * hop / cfg.sample_rate
    seconds = np.arange(frames) * hop / cfg.sample_rate - middle
    ramp = np.zeros(frames) if spec.track else (
        float(info["own_doppler_hz"]) + float(info["drift_hz_s"]) * seconds)
    spectrum = EvolvingSpectrum(
        [Component(freqs=freqs, weights=weights, centre_hz=0.0,
                   gain=np.ones(frames), shift=ramp, width=np.ones(frames))],
        smooth_hz=max(float(info["spread_hz"]) / 12.0,
                      1.2 * cfg.sample_rate / max(block, 1)))

    # The spread that gets quoted is the one libration actually puts on the echo.
    # Six seconds of audio cannot resolve a hundredth of a Hz, but that is a
    # limit of the transform, and the report is about the path.
    shift, _ = spectrum.moments()
    info["shift_hz"] = shift
    info["tuned_out_hz"] = 0.0
    if cfg.retune:
        info["tuned_out_hz"] = shift
        spectrum.retune(-shift)
    info["audible_fraction"] = audible_fraction(
        spectrum.grid, spectrum.mean_psd(), cfg.freq, cfg.bandwidth, cfg.sample_rate)
    if spec.track:
        # Tracking took out the offset and the ramp; the dial took out whatever
        # the disc itself was offset by.  Say so as one number.
        info["tuned_out_hz"] = float(info["own_doppler_hz"]) + float(info["tuned_out_hz"])
    info["residual_drift_hz_s"] = 0.0 if spec.track else float(info["drift_hz_s"])
    info["sounds_like"] = sounds_like(float(info["spread_hz"]),
                                      float(info["audible_fraction"]))

    # The echo is late: 2.4 to 2.7 seconds, which is the whole charm of it.
    delay = int(round(spec.delay_s * cfg.sample_rate))
    late = np.zeros_like(env)
    if delay < env.size:
        late[delay:] = env[:env.size - delay]

    process = evolving_channel(
        env.size, cfg.sample_rate, spectrum, cfg.freq, rngs["scatter"], block)
    if (spec.faraday_db or 0.0) > 0.5:
        process = process * faraday_fade(
            env.size, cfg.sample_rate, rngs["scatter"],
            float(spec.faraday_db), float(spec.faraday_period_s or 600.0))
    depth = 0.0 if cfg.scintillation_db is None else float(cfg.scintillation_db)
    info["scintillation_db"] = depth
    if depth > 0:
        process = process * scintillate(
            env.size, cfg.sample_rate, rngs["scatter"], depth,
            float(cfg.scintillation_rate or 0.1))
    return apply_channel(late, cfg.freq, cfg.sample_rate, process), info


def _station_scatter(cfg: Config, band: Band, cell: Cell, mode: str):
    """Scatter the other stations too -- same front, their own path into it.

    This is why no two stations on rain scatter sound alike.  They are working
    the same cell, so its character and its rain rate carry over, but each one
    looks into it from somewhere else: its own elevation, its own corner of the
    cloud, its own cores.  One is a clean note, the next is a rasp.
    """
    def apply(env: np.ndarray, freq: float, rng: np.random.Generator):
        other = draw_weather(cfg, mode, rng, character=cell.character,
                             rate_mm_h=cell.rate_mm_h)
        samples, info = cell_doppler(
            other, band, rng, scatterers=min(cfg.scatterers, 2400))
        freqs = np.concatenate([s.freqs for s in samples])
        weights = np.concatenate([s.weights for s in samples])
        grid, psd = doppler_spectrum(freqs, weights)
        grid = grid - float(info["shift_hz"])       # they tune their own note, too
        process = channel(env.size, cfg.sample_rate, grid, psd, freq, rng)
        audio = apply_channel(env, freq, cfg.sample_rate, process)
        return audio, f"{info['cell']} cell, spread {info['spread_hz']:.0f} Hz"
    return apply


def render(text: str, config: Config | None = None) -> Render:
    """Render ``text`` as Morse audio under ``config``'s band conditions."""
    cfg = config or Config()
    rngs = streams(cfg.seed)
    band = cfg.band_object()
    mode = mode_name(cfg.scatter)
    if mode not in MODES:
        raise ValueError(f"unknown scatter mode: {cfg.scatter!r}")

    words, unknown = parse(text)
    timing = Timing(cfg.wpm, cfg.effective_wpm)
    elements = timeline(words, timing)
    keyed = duration(elements)

    # The Moon has to be drawn before the buffer is sized: the echo arrives
    # after the message has finished, and it has to have somewhere to land.
    moon = None
    tail = 0.0
    if mode == "moon":
        moon = draw_moon(
            rngs["weather"], band, distance_km=cfg.moon_distance_km,
            libration_deg_day=cfg.libration_deg_day,
            range_rate_mps=cfg.moon_range_rate_mps,
            range_accel_mps2=cfg.moon_accel_mps2,
            scatter_law=cfg.moon_scatter_law, faraday_db=cfg.faraday_db,
            patches=cfg.scatterers, track=cfg.doppler_track)
        tail = moon.delay_s

    wanted = max(1, int(np.ceil((keyed + 2 * cfg.pad + tail) * cfg.sample_rate)))
    if wanted > MAX_SAMPLES:
        raise ValueError(
            f"that is {wanted / cfg.sample_rate / 60:.0f} minutes of audio; send it "
            f"faster, shorten it, or drop --rate")
    # Everything downstream is a transform over the whole length, so work at a
    # length the FFT likes and trim the few extra samples of silence off at the
    # end: the same audio, several times faster.
    n = fast_length(wanted)

    direct, env = keyed_tone(
        elements, cfg.sample_rate, cfg.tone_spec(), rngs["signal"], pad=cfg.pad, length=n
    )

    scatter_info: dict[str, object] = {}
    cell: Cell | None = None
    if cfg.scatter_spec().active:
        if mode in WEATHER_MODES:
            scattered, scatter_info, cell = _weather_path(cfg, env, band, mode, rngs)
        elif mode == "iono":
            scattered, scatter_info = _iono_path(cfg, env, band, rngs)
        elif mode == "moon":
            scattered, scatter_info = _moon_path(cfg, env, band, moon, rngs)
        else:
            scattered, scatter_info = _aurora_path(cfg, env, band, rngs)
        direct_amp, scatter_amp = rician_weights(cfg.rician_db)
        # The rain on the way is charged against the signal-to-noise ratio below,
        # not here: scaling the whole signal would cancel out when the noise is
        # set from it, and a path loss that changes nothing is a lie.
        signal = direct_amp * direct + scatter_amp * scattered
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
        # Rain is a two-edged thing: the cell that returns the signal is also
        # what the signal has to cross, and past about 50 mm/h on 10 GHz the
        # attenuation wins.
        offset -= float(scatter_info.get("attenuation_db", 0.0))
        effective_snr = float(cfg.snr_db) + offset

    noise_info: dict[str, object] = {}
    out = signal
    if noisy:
        station_scatter = None
        if cell is not None and cfg.qrm_scatter and cfg.qrm_count:
            station_scatter = _station_scatter(cfg, band, cell, mode)
        bus, noise_info = build_noise(n, cfg.sample_rate, cfg.freq, cfg.noise_spec(),
                                     rngs, scatter=station_scatter)
        if down_power > 1e-18:
            # The floor has unit RMS, so this single gain sets S/N in the pass band.
            noise_gain = float(np.sqrt(down_power) / db_to_amp(float(effective_snr)))
        else:
            noise_gain = 0.25   # nothing of the signal survived: just the band, then
        out = signal + noise_gain * bus

    out = out[:wanted]
    key_down, key_up = key_down[:wanted], key_up[:wanted]

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

    # QRSS: the message is not listened to, it is read off a waterfall in a bin
    # about 1/dit wide, and that narrowness is the whole point -- as long as
    # nothing on the path smears the trace wider than the bin.
    qrss: dict[str, object] = {}
    if timing.unit >= QRSS_DIT_S:
        detection = 1.0 / timing.unit
        gain = 10.0 * float(np.log10(max(cfg.bandwidth, 1.0) / detection))
        spread = float(scatter_info.get("spread_hz", 0.0) or 0.0)
        smear = 10.0 * float(np.log10(max(spread / detection, 1.0)))
        qrss = {
            "label": qrss_label(timing.unit),
            "drift_hz": cfg.drift_hz,
            "dit_s": timing.unit,
            "bandwidth_hz": detection,
            "processing_gain_db": gain,
            "smear_db": -smear,
            "smeared": spread > detection,
            "waterfall_snr_db": (None if effective_snr is None
                                 else float(effective_snr) + gain - smear),
        }

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
        "duration": wanted / cfg.sample_rate,
        "sample_rate": cfg.sample_rate,
        "tone_hz": cfg.freq,
        "band": band.label,
        "wavelength_mm": band.wavelength_m * 1000.0,
        "hz_per_mps": float(band.doppler_hz(1.0)),
        "scatter": scatter_info,
        "qrss": qrss,
        "snr_db": cfg.snr_db,
        "effective_snr_db": effective_snr,
        "measured_snr_db": measured,
        "noise": noise_info,
        "seed": cfg.seed,
        "config": asdict(cfg),
    }
    return Render(out.astype(np.float64), cfg.sample_rate, meta)
