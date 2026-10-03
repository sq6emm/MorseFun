"""What a receiver hears besides the wanted signal.

The band is modelled as four separate things, mixed on one bus and then run
through the receiver's IF filter:

* an atmospheric noise floor, pink-tilted rather than flat white;
* static crashes (QRN) arriving at random, each a decaying broadband burst;
* other CW stations (QRM), each with a callsign a real licensing authority
  could have issued, its own speed, tone and fading;
* heterodynes, the steady drifting whistles of a carrier sitting in the pass band.

The floor is normalised to unit RMS after filtering, so every other level is
quoted in dB relative to it and the caller only has to pick one gain to hit a
wanted signal-to-noise ratio.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dsp import band_response, bandpass, db_to_amp, rms, smooth_noise
from .morse import Element, Timing, parse, timeline
from .synth import ToneSpec, keyed_tone, keying_envelope
from .traffic import Station, draw_station, random_call, station_from_call

#: What the neighbours are sending.  Short, like real QRM heard in passing.
QRM_PATTERNS = (
    "cq cq de {call} {call} k",
    "{call} de {other} ur rst 579 579 <BT> hw?",
    "test {call}",
    "{call} 5nn tu",
    "qrl? de {call}",
    "de {call} tu 73 <SK>",
    "{other} de {call} ok fb om",
    "r r {other} de {call} gm es tnx fer call <BT> ur rst 559 559",
    "{other} de {call} qth near {qth} {qth} <BT> name {name} {name} <AR>",
    "cq dx cq dx de {call} {call} {call} k",
    "{other} de {call} ur 559 559 in {loc} {loc} hw? <KN>",
    "cq cq de {call} {call} {square} k",
)

#: A contest weekend: exchanges, serials, zones, pile-ups and nobody chatting.
CONTEST_PATTERNS = (
    "cq test {call} {call} test",
    "test {call} {call}",
    "{other} 5nn {zone}",
    "{other} tu 5nn {zone} {zone}",
    "{call} 599 {zone} tu",
    "{other} r 5nn {nr} {nr}",
    "tu {call} test",
    "nr {nr} {nr} tu",
    "{other} {other} de {call} 5nn {nr} k",
    "agn agn",
    "qrz? {call} test",
    "{other} ur 5nn {nr} bk",
    "{other} de {call} {call}",
    "cq cq test de {call} {call} test",
)

#: How long a station listens between transmissions, seconds.
PAUSE_S = {"ragchew": (1.0, 5.0), "contest": (0.3, 1.8)}


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
    qrm_style: str = "ragchew"   # ragchew | contest | mixed: what they are sending
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


def station_text(style: str, station: Station | str, rng: np.random.Generator) -> str:
    """One transmission from a station working in ``style``.

    The station brings its own callsign, name, town and locator, all from the
    same country, so a neighbour giving a QTH gives one its prefix allows.
    """
    if isinstance(station, str):
        station = station_from_call(station, rng)
    contest = style == "contest" or (style == "mixed" and rng.random() < 0.5)
    pattern = str(rng.choice(CONTEST_PATTERNS if contest else QRM_PATTERNS))
    return pattern.format(
        call=station.call.lower(), other=random_call(rng),
        nr=int(rng.integers(1, 1500)), zone=station.zone,
        qth=station.qth or "here", name=station.name,
        loc=station.locator.lower(), square=station.square.lower())


def station_timeline(style: str, station: Station | str, wpm: float, seconds: float,
                     rng: np.random.Generator) -> tuple[list, str]:
    """Everything one station sends in ``seconds``: it keeps going, with pauses.

    A station that is on the band stays on it -- calls, listens, calls again --
    so the timeline is transmission, pause, transmission until the render is
    full, each transmission freshly drawn.  Returns the elements and the first
    text, for the report.
    """
    lo, hi = PAUSE_S["contest" if style == "contest" else "ragchew"]
    timing = Timing(wpm)
    elements: list[Element] = []
    first = ""
    total = 0.0
    while total < seconds:
        text = station_text(style, station, rng)
        first = first or text
        words, _ = parse(text)
        part = timeline(words, timing)
        elements.extend(part)
        pause = float(rng.uniform(lo, hi))
        elements.append(Element(False, pause, "word-gap"))
        total += sum(e.seconds for e in part) + pause
    return elements, first


def qrm(
    n: int, sample_rate: int, center: float, spec: NoiseSpec, rng: np.random.Generator,
    scatter=None,
) -> tuple[np.ndarray, list[str]]:
    """Other stations working through the pass band.

    Each one has its own callsign, speed, tone, level and fading, keeps sending
    for the whole render with listening gaps between overs, and starts wherever
    it was when you tuned in.  In ``contest`` style the exchanges are serials
    and zones at 26 to 40 wpm and the stations sit close to the frequency,
    because that is what a pile-up is.

    ``scatter``, if given, is called with ``(envelope, tone, rng)`` and returns
    the station already scattered off its own cell plus a note about it.  On a
    scatter path that is the whole point: the neighbours are in the same rain,
    but none of them is on the same path through it, so none of them sounds the
    same.  A scattered station gets no fading of its own -- the cell gives it
    more flutter than a fading rig ever would.
    """
    out = np.zeros(n)
    notes: list[str] = []
    seconds = n / sample_rate
    contest = spec.qrm_style == "contest"
    for index in range(max(0, spec.qrm_count)):
        station = draw_station(rng)
        call = station.call.lower()
        wpm = float(rng.uniform(*spec.qrm_wpm))
        level_db = float(rng.uniform(*spec.qrm_db))
        # Sit somewhere in the pass band.  Ragchewers keep their distance; a
        # pile-up sits right on top of you, and the first one in it always
        # does, because a pile-up with nobody on your frequency is not one.
        nearest = 0.03 if contest else 0.18
        farthest = 0.09 if contest and index == 0 else 0.75
        offset = (float(rng.uniform(nearest, farthest) * spec.bandwidth)
                  * (1 if rng.random() < 0.5 else -1))
        start = float(rng.uniform(-0.6, 0.5)) * seconds
        elements, text = station_timeline(spec.qrm_style, station, wpm,
                                          seconds - min(start, 0.0), rng)
        station = ToneSpec(
            freq=max(80.0, center + offset),
            rise_ms=float(rng.uniform(3.0, 9.0)),
            level=db_to_amp(level_db),
            drift_hz=0.0 if scatter else float(rng.uniform(0.0, 4.0)),
            drift_rate=0.05,
            qsb_db=0.0 if scatter else float(rng.uniform(2.0, 14.0)),
            qsb_rate=float(rng.uniform(0.1, 0.5)),
        )
        note = (f"{call} at {station.freq - center:+.0f} Hz, {wpm:.0f} wpm, "
                f"{level_db:+.0f} dB: \"{text}\"")
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
