"""What a receiver hears besides the wanted signal.

The band is modelled as four separate things, mixed on one bus and then run
through the receiver's IF filter:

* an atmospheric noise floor, pink-tilted rather than flat white;
* static crashes (QRN) arriving at random, each a decaying broadband burst;
* other CW stations (QRM), each with its own callsign, speed, tone and fading;
* heterodynes, the steady drifting whistles of a carrier sitting in the pass band.

The floor is normalised to unit RMS after filtering, so every other level is
quoted in dB relative to it and the caller only has to pick one gain to hit a
wanted signal-to-noise ratio.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dsp import band_response, bandpass, db_to_amp, rms, smooth_noise
from .morse import Timing, parse, timeline
from .synth import ToneSpec, keyed_tone, keying_envelope

CALL_PREFIXES = (
    "sp", "sq", "dl", "ok", "oh", "sm", "la", "ea", "on", "pa", "yo", "yu",
    "g", "gm", "f", "i", "ua", "ur", "lz", "s5", "9a", "k", "w", "n", "ve", "ja",
)

#: What the neighbours are sending.  Short, like real QRM heard in passing.
QRM_PATTERNS = (
    "cq cq de {call} {call} k",
    "{call} de {other} ur rst 579 579 <BT> hw?",
    "test {call}",
    "{call} 5nn tu",
    "qrl? de {call}",
    "de {call} tu 73 <SK>",
    "{other} de {call} ok fb om",
)


@dataclass
class NoiseSpec:
    """How bad the band is."""

    bandwidth: float = 500.0     # receiver IF filter, Hz
    snr_db: float | None = 10.0  # signal to noise floor in that bandwidth; None = no noise
    tilt: float = 0.5            # atmospheric pink tilt, 0 = white
    crash_rate: float = 0.8      # static crashes per second
    crash_db: float = 22.0       # crash peak above the noise floor, dB
    crash_decay_ms: tuple[float, float] = (2.0, 30.0)
    qrm_count: int = 1           # other CW stations in the pass band
    qrm_db: tuple[float, float] = (-6.0, 8.0)  # their level above the floor, dB
    qrm_wpm: tuple[float, float] = (14.0, 32.0)
    birdie_count: int = 0        # drifting carriers
    birdie_db: float = 4.0


def atmospheric_floor(
    n: int, sample_rate: int, center: float, spec: NoiseSpec, rng: np.random.Generator
) -> np.ndarray:
    """Band-limited noise floor with a 1/f^tilt atmospheric slope, unit RMS."""
    white = rng.standard_normal(n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
    if spec.tilt:
        slope = np.ones_like(freqs)
        nonzero = freqs > 0
        slope[nonzero] = np.power(1000.0 / freqs[nonzero], spec.tilt)
        slope[~nonzero] = 0.0
        spectrum *= slope
    spectrum *= band_response(freqs, center, spec.bandwidth)
    out = np.fft.irfft(spectrum, n)
    level = rms(out)
    return out / level if level > 1e-12 else out


def static_crashes(
    n: int, sample_rate: int, center: float, spec: NoiseSpec, rng: np.random.Generator
) -> np.ndarray:
    """Impulsive QRN: Poisson arrivals, log-normal strengths, scaled to peak."""
    out = np.zeros(n)
    if spec.crash_rate <= 0 or n == 0:
        return out
    count = int(rng.poisson(spec.crash_rate * n / sample_rate))
    lo, hi = spec.crash_decay_ms
    for _ in range(count):
        start = int(rng.integers(0, n))
        tau = rng.uniform(lo, hi) / 1000.0
        length = min(n - start, int(8 * tau * sample_rate) + 2)
        t = np.arange(length) / sample_rate
        burst = rng.standard_normal(length) * np.exp(-t / tau)
        out[start : start + length] += rng.lognormal(0.0, 0.7) * burst
    out = bandpass(out, sample_rate, center, spec.bandwidth)
    peak = np.max(np.abs(out)) if out.size else 0.0
    if peak > 1e-12:
        out *= db_to_amp(spec.crash_db) / peak
    return out


def random_call(rng: np.random.Generator) -> str:
    """A plausible callsign: prefix, digit, one to three letters."""
    prefix = str(rng.choice(CALL_PREFIXES))
    digit = str(int(rng.integers(0, 10)))
    letters = "".join(chr(int(c)) for c in rng.integers(97, 123, size=int(rng.integers(1, 4))))
    return prefix + digit + letters


def qrm(
    n: int, sample_rate: int, center: float, spec: NoiseSpec, rng: np.random.Generator,
    scatter=None,
) -> tuple[np.ndarray, list[str]]:
    """Other stations working through the pass band.

    ``scatter``, if given, is called with ``(envelope, tone, rng)`` and returns
    the station already scattered off its own cell plus a note about it.  On a
    scatter path that is the whole point: the neighbours are in the same rain,
    but none of them is on the same path through it, so none of them sounds the
    same.  A scattered station gets no fading of its own -- the cell gives it
    more flutter than a fading rig ever would.
    """
    out = np.zeros(n)
    notes: list[str] = []
    for _ in range(max(0, spec.qrm_count)):
        call = random_call(rng)
        text = str(rng.choice(QRM_PATTERNS)).format(call=call, other=random_call(rng))
        wpm = float(rng.uniform(*spec.qrm_wpm))
        level_db = float(rng.uniform(*spec.qrm_db))
        # Sit somewhere in or just outside the pass band, never right on top of us.
        offset = float(rng.uniform(0.18, 0.75) * spec.bandwidth) * (1 if rng.random() < 0.5 else -1)
        words, _ = parse(text)
        elements = timeline(words, Timing(wpm))
        station = ToneSpec(
            freq=max(80.0, center + offset),
            rise_ms=float(rng.uniform(3.0, 9.0)),
            level=db_to_amp(level_db),
            drift_hz=0.0 if scatter else float(rng.uniform(0.0, 4.0)),
            drift_rate=0.05,
            qsb_db=0.0 if scatter else float(rng.uniform(2.0, 14.0)),
            qsb_rate=float(rng.uniform(0.1, 0.5)),
        )
        start = float(rng.uniform(-0.5, 1.0)) * n / sample_rate
        note = f"{call} at {station.freq - center:+.0f} Hz, {wpm:.0f} wpm, {level_db:+.0f} dB"
        if scatter is None:
            audio, _ = keyed_tone(elements, sample_rate, station, rng, length=n, offset=start)
        else:
            env = keying_envelope(elements, sample_rate, station.rise_ms,
                                  length=n, offset=start)
            audio, detail = scatter(env, station.freq, rng)
            audio = audio * station.level
            note += f", {detail}"
        out += bandpass(audio, sample_rate, center, spec.bandwidth)
        notes.append(note)
    return out, notes


def heterodynes(
    n: int, sample_rate: int, center: float, spec: NoiseSpec, rng: np.random.Generator
) -> tuple[np.ndarray, list[str]]:
    """Steady carriers: a whistle that drifts but never says anything."""
    out = np.zeros(n)
    notes: list[str] = []
    for _ in range(max(0, spec.birdie_count)):
        offset = float(rng.uniform(-0.45, 0.45) * spec.bandwidth)
        freq = max(80.0, center + offset)
        wander = 2.0 * smooth_noise(n, sample_rate, 0.03, rng)
        phase = 2 * np.pi * np.cumsum(freq + wander) / sample_rate
        level = db_to_amp(spec.birdie_db + float(rng.uniform(-4.0, 4.0)))
        out += level * np.sin(phase)
        notes.append(f"carrier at {offset:+.0f} Hz, {spec.birdie_db:+.0f} dB")
    if notes:
        out = bandpass(out, sample_rate, center, spec.bandwidth)
    return out, notes


def build_noise(
    n: int, sample_rate: int, center: float, spec: NoiseSpec,
    rngs: dict[str, np.random.Generator], scatter=None,
) -> tuple[np.ndarray, dict[str, object]]:
    """Mix the whole band onto one bus whose noise floor has unit RMS.

    ``rngs`` holds one independent generator per component, so adding static
    crashes does not change which stations are on the band.
    """
    floor = atmospheric_floor(n, sample_rate, center, spec, rngs["floor"])
    bus = floor.copy()
    info: dict[str, object] = {"floor_rms": 1.0}

    crashes = static_crashes(n, sample_rate, center, spec, rngs["crashes"])
    if np.any(crashes):
        bus += crashes
        info["crashes"] = int(round(spec.crash_rate * n / sample_rate))

    stations, notes = qrm(n, sample_rate, center, spec, rngs["qrm"], scatter)
    if notes:
        bus += stations
        info["qrm"] = notes

    birdies, bnotes = heterodynes(n, sample_rate, center, spec, rngs["birdies"])
    if bnotes:
        bus += birdies
        info["birdies"] = bnotes

    return bus, info
