"""Command line front end: text in, WAV files out."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from dataclasses import replace
from pathlib import Path

from .cell import parse_character
from .play import PlaybackError, describe_players, find_player, play
from .profiles import DEFAULT_PROFILE, DESCRIPTIONS, GROUPS, PROFILES
from .render import Config, Render, apply_qrss, render
from .wav import write_wav

DEFAULT_TEXT = "cq cq de sq6emm sq6emm k"

#: command line option -> Config field
OVERRIDES = {
    "wpm": "wpm",
    "effective_wpm": "effective_wpm",
    "rise_ms": "rise_ms",
    "tone": "freq",
    "drift": "drift_hz",
    "drift_rate": "drift_rate",
    "qsb": "qsb_db",
    "qsb_rate": "qsb_rate",
    "hum": "hum_depth",
    "hum_hz": "hum_hz",
    "snr": "snr_db",
    "bandwidth": "bandwidth",
    "tilt": "tilt",
    "qrn": "crash_rate",
    "qrn_db": "crash_db",
    "qrm": "qrm_count",
    "qrm_db": "qrm_db",
    "birdies": "birdie_count",
    "birdie_db": "birdie_db",
    "band": "band",
    "scatter": "scatter",
    "rician": "rician_db",
    "retune": "retune",
    "scint": "scintillation_db",
    "scint_rate": "scintillation_rate",
    "doppler_shift": "doppler_shift_hz",
    "doppler_spread": "doppler_spread_hz",
    "scatterers": "scatterers",
    "elevation": "elevation_deg",
    "wind": "wind_mps",
    "wind_azimuth": "wind_azimuth_deg",
    "turbulence": "turbulence_mps",
    "path_km": "path_km",
    "weather_level": "weather_level",
    "rain_rate": "rain_rate",
    "snow_rate": "snow_rate",
    "snow_wet": "snow_wet",
    "cell": "cell_character",
    "cores": "cores",
    "updraft": "updraft_mps",
    "shear": "shear_mps_km",
    "squint": "squint_deg",
    "beamwidth": "beamwidth_deg",
    "height": "height_km",
    "depth": "depth_km",
    "evolve": "evolve",
    "evolve_rate": "evolve_rate_hz",
    "qrm_scatter": "qrm_scatter",
    "libration": "libration_deg_day",
    "moon_distance": "moon_distance_km",
    "range_rate": "moon_range_rate_mps",
    "moon_accel": "moon_accel_mps2",
    "moon_law": "moon_scatter_law",
    "faraday": "faraday_db",
    "doppler_track": "doppler_track",
    "baseline_km": "baseline_km",
    "altitude": "altitude_km",
    "plane_speed": "plane_speed_mps",
    "plane_heading": "plane_heading_deg",
    "plane_length": "plane_length_m",
    "iono_modes": "iono_modes",
    "layer_rate": "layer_rate_mps",
    "layer_churn": "layer_turbulence_mps",
    "takeoff": "takeoff_deg",
    "aurora_drift": "aurora_drift_mps",
    "aurora_spread": "aurora_spread_mps",
    "aurora_toward": "aurora_toward",
    "aurora_activity": "aurora_activity",
    "aurora_burst": "aurora_burst_s",
    "rate": "sample_rate",
    "pad": "pad",
    "peak": "peak",
    "seed": "seed",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="morsefun",
        description="Key a message in Morse and play it, with as much or as little "
                    "radio noise as you want on it. Writes a WAV file only if you ask.",
        epilog='examples:\n'
               '  morsefun "cq cq de sq6emm sq6emm k" --wpm 23 --tone 600\n'
               '  morsefun "cq de sq6emm k" --profile noisy --repeat 3\n'
               '  morsefun "cq de sq6emm k" -o cq.wav',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("text", nargs="*", help=f"message to key (default: {DEFAULT_TEXT!r})")
    p.add_argument("-o", "--out", metavar="FILE",
                   help="write a WAV file instead of playing it")
    p.add_argument("--batch", metavar="FILE", help="key one message per line of FILE")
    p.add_argument("--outdir", default=".", help="where batch files go (default: .)")
    p.add_argument("--profile", default=DEFAULT_PROFILE, choices=sorted(PROFILES),
                   help=f"band conditions (default: {DEFAULT_PROFILE})")
    p.add_argument("--list-profiles", action="store_true", help="show the profiles and exit")
    p.add_argument("--list-players", action="store_true",
                   help="show the audio players looked for, and which are installed")
    p.add_argument("--json", action="store_true", help="print the render details as JSON")
    p.add_argument("-q", "--quiet", action="store_true", help="print nothing but errors")

    k = p.add_argument_group("keying")
    k.add_argument("--wpm", type=float, help="keying speed in words per minute (default: 23)")
    k.add_argument("--effective-wpm", type=float, metavar="WPM",
                   help="Farnsworth: stretch the gaps to this overall speed")
    k.add_argument("--rise-ms", type=float, help="envelope rise and fall in ms (default: 5)")
    k.add_argument("--qrss", type=float, metavar="SECONDS",
                   help="QRSS: a dit this many seconds long, read off a waterfall "
                        "instead of by ear (3, 10, 30, 60, 120). Slows the envelope "
                        "down to match and drops the sample rate to 8 kHz")

    t = p.add_argument_group("tone")
    t.add_argument("--tone", type=float, help="tone frequency in Hz (default: 600)")
    t.add_argument("--drift", type=float, metavar="HZ", help="peak frequency wander")
    t.add_argument("--drift-rate", type=float, metavar="HZ", help="how fast it wanders")
    t.add_argument("--qsb", type=float, metavar="DB", help="fading depth in dB")
    t.add_argument("--qsb-rate", type=float, metavar="HZ", help="fading rate")
    t.add_argument("--hum", type=float, metavar="DEPTH", help="mains hum on the carrier, 0..1")
    t.add_argument("--hum-hz", type=float, help="mains frequency (default: 50)")

    w = p.add_argument_group(
        "propagation",
        "scatter off the weather. Scattering is bistatic, so what is heard is "
        "the motion along the bisector of the two paths -- straight up for a "
        "symmetric path, which is why rain scatter is mostly the sound of air "
        "and drops going up and down, scaled by the elevation. Everything here "
        "is drawn fresh for every render unless you pin it, so no two clouds "
        "are alike; --seed brings one back.")
    w.add_argument("--band", metavar="FREQ",
                   help="operating frequency: 10G, 10.368GHz, 1296, 144M, 3cm (default: 10G)")
    w.add_argument("--scatter",
                   choices=("none", "rain", "snow", "aurora", "iono", "skywave",
                            "moon", "eme", "aircraft", "air", "plane"),
                   help="what the signal bounces off: weather, an auroral curtain, "
                        "a low-band skywave hop (iono), an airliner (air), or "
                        "the Moon (eme)")
    w.add_argument("--rain-rate", type=float, metavar="MM_H", help="rain rate (default: 12)")
    w.add_argument("--snow-rate", type=float, metavar="MM_H",
                   help="snowfall, water equivalent (default: 4)")
    w.add_argument("--snow-wet", action="store_true", default=None,
                   help="melting snow: the radar bright band, far stronger than dry")
    w.add_argument("--cell", type=parse_character, metavar="KIND",
                   help="cell character: auto (default), stratiform, showers, "
                        "convective, storm, or a number 0..1")
    w.add_argument("--cores", type=int, metavar="N",
                   help="scattering centres in the volume, 1 to 4 (default: drawn)")
    w.add_argument("--updraft", type=float, metavar="MPS",
                   help="bulk vertical motion in the cores; this is what shifts the note")
    w.add_argument("--shear", type=float, metavar="MPS_KM",
                   help="how much the wind changes through the volume")
    w.add_argument("--elevation", type=float, metavar="DEG",
                   help="elevation of the common volume from this end (default: drawn)")
    w.add_argument("--squint", type=float, metavar="DEG",
                   help="how far the cell sits off the line between the stations")
    w.add_argument("--beamwidth", type=float, metavar="DEG",
                   help="antenna beamwidth, so how big the shared volume is")
    w.add_argument("--height", type=float, metavar="KM",
                   help="height of the common volume (default: drawn)")
    w.add_argument("--depth", type=float, metavar="KM",
                   help="how deep a slice of weather is sampled")
    w.add_argument("--evolve-rate", type=float, metavar="HZ",
                   help="how fast the cell rearranges itself while you listen")
    w.add_argument("--no-evolve", dest="evolve", action="store_false", default=None,
                   help="hold the cell still: one fixed spectrum for the whole message")
    w.add_argument("--no-qrm-scatter", dest="qrm_scatter", action="store_false",
                   default=None,
                   help="other stations come in direct instead of off their own cell")
    w.add_argument("--wind", type=float, metavar="MPS", help="wind through the volume")
    w.add_argument("--wind-azimuth", type=float, metavar="DEG",
                   help="wind direction (default: drawn at random each render)")
    w.add_argument("--turbulence", type=float, metavar="MPS",
                   help="velocity spread inside the volume; this sets most of the hiss")
    w.add_argument("--path-km", type=float, metavar="KM",
                   help="rain or snow along the path, for attenuation")
    w.add_argument("--aurora-drift", type=float, metavar="MPS",
                   help="bulk drift of the irregularities (default: 600)")
    w.add_argument("--aurora-spread", type=float, metavar="MPS",
                   help="turbulent spread of the drift (default: 200)")
    w.add_argument("--aurora-toward", action="store_true", default=None,
                   help="curtain drifting towards you, so shifted up")
    w.add_argument("--aurora-activity", type=float, metavar="FRACTION",
                   help="how much of the time it is alive, 0..1 (default: 0.55)")
    w.add_argument("--aurora-burst", type=float, metavar="S",
                   help="length of a surge in seconds (default: 4)")
    w.add_argument("--libration", type=float, metavar="DEG_DAY",
                   help="EME: apparent rotation of the Moon, 0.2 (libration minimum) "
                        "to 8; this sets the spread (default: drawn)")
    w.add_argument("--moon-distance", type=float, metavar="KM",
                   help="EME: 356500 at perigee to 406700 at apogee (default: drawn)")
    w.add_argument("--range-rate", type=float, metavar="MPS",
                   help="EME: how fast the Moon is closing, up to ±465 m/s, which is "
                        "the self-Doppler (default: drawn)")
    w.add_argument("--moon-accel", type=float, metavar="MPS2",
                   help="EME: how fast that is changing; this is what slopes a QRSS "
                        "trace across the screen")
    w.add_argument("--moon-law", type=float, metavar="N",
                   help="EME: cos^N scattering across the disc (default: drawn 1.5-3)")
    w.add_argument("--faraday", type=float, metavar="DB",
                   help="EME: depth of the polarisation fading (default: from the band, "
                        "22 dB on 2 m, nothing on 10 GHz)")
    w.add_argument("--no-doppler-track", dest="doppler_track", action="store_false",
                   default=None,
                   help="EME: do not follow the Doppler, so the trace slopes away")
    w.add_argument("--echo-test", action="store_true",
                   help="EME: hear your own keying as well, so the echo answers it "
                        "2.5 s later (the same as --rician 6)")
    w.add_argument("--baseline-km", type=float, metavar="KM",
                   help="aircraft scatter: how far apart the two stations are")
    w.add_argument("--altitude", type=float, metavar="KM",
                   help="aircraft scatter: how high it is flying (default: drawn 7-12.5)")
    w.add_argument("--plane-speed", type=float, metavar="MPS",
                   help="aircraft scatter: how fast (default: drawn 180-290)")
    w.add_argument("--plane-heading", type=float, metavar="DEG",
                   help="aircraft scatter: 90 crosses the path, 0 follows it")
    w.add_argument("--plane-length", type=float, metavar="M",
                   help="aircraft scatter: how long the reflector is, which sets "
                        "the roughness on the note")
    w.add_argument("--iono-modes", type=int, metavar="N",
                   help="low band: hops or magneto-ionic components arriving, 1 to 3")
    w.add_argument("--layer-rate", type=float, metavar="MPS",
                   help="low band: how fast the reflecting layer is moving, a few "
                        "tenths overnight and metres a second at dawn")
    w.add_argument("--layer-churn", type=float, metavar="MPS",
                   help="low band: spread of those vertical motions")
    w.add_argument("--takeoff", type=float, metavar="DEG",
                   help="low band: take-off angle at the reflection point")
    w.add_argument("--rician", type=float, metavar="DB",
                   help="direct-to-scattered power ratio; the default -99 is pure scatter")
    w.add_argument("--doppler-shift", type=float, metavar="HZ",
                   help="set the aurora shift in audio Hz instead of from physics")
    w.add_argument("--doppler-spread", type=float, metavar="HZ",
                   help="set the aurora spread in audio Hz instead of from physics")
    w.add_argument("--scint", type=float, metavar="DB",
                   help="slow extra fading on top of the Rayleigh flutter")
    w.add_argument("--scint-rate", type=float, metavar="HZ", help="rate of that fading")
    w.add_argument("--scatterers", type=int, metavar="N",
                   help="drops, flakes or auroral cells to sample (default: 6000)")
    w.add_argument("--no-retune", dest="retune", action="store_false", default=None,
                   help="leave the return where the Doppler put it instead of tuning it back")
    w.add_argument("--no-weather-level", dest="weather_level", action="store_false",
                   default=None,
                   help="do not let reflectivity set the signal strength "
                        "(power lost outside the filter still counts)")

    b = p.add_argument_group("band")
    b.add_argument("--snr", type=float, metavar="DB",
                   help="signal to noise floor in the filter bandwidth")
    b.add_argument("--no-noise", action="store_true", help="bare tone, no band at all")
    b.add_argument("--bandwidth", type=float, metavar="HZ",
                   help="receiver IF filter width (default: 500)")
    b.add_argument("--tilt", type=float, help="atmospheric 1/f tilt, 0 for white noise")
    b.add_argument("--qrn", type=float, metavar="PER_S", help="static crashes per second")
    b.add_argument("--qrn-db", type=float, metavar="DB", help="crash peak above the floor")
    b.add_argument("--qrm", type=int, metavar="N", help="other CW stations in the pass band")
    b.add_argument("--qrm-db", type=float, nargs=2, metavar=("MIN", "MAX"),
                   help="their level above the floor, dB")
    b.add_argument("--birdies", type=int, metavar="N", help="drifting carriers")
    b.add_argument("--birdie-db", type=float, metavar="DB", help="carrier level above the floor")

    o = p.add_argument_group("output")
    o.add_argument("--rate", type=int, help="sample rate in Hz (default: 44100)")
    o.add_argument("--pad", type=float, metavar="S", help="silence before and after (default: 0.6)")
    o.add_argument("--peak", type=float, help="peak level, 0..1 (default: 0.89)")
    o.add_argument("--no-limit", action="store_true", help="skip the AGC-style soft limiter")
    o.add_argument("--seed", type=int, help="reuse a seed to get the same band back")

    a = p.add_argument_group("playback")
    a.add_argument("-p", "--play", action="store_true",
                   help="play it (the default when no file is being written)")
    a.add_argument("--player", metavar="CMD",
                   help='player command, ending in the stdin argument, e.g. "ffplay -nodisp -autoexit -"')
    a.add_argument("--repeat", type=int, default=1, metavar="N", help="play it N times")
    a.add_argument("--gap", type=float, default=1.5, metavar="S",
                   help="silence between repeats in seconds (default: 1.5)")
    return p


def config_from_args(args: argparse.Namespace) -> Config:
    cfg = Config()
    for field, value in PROFILES[args.profile].items():
        setattr(cfg, field, value)
    for option, field in OVERRIDES.items():
        value = getattr(args, option, None)
        if value is not None:
            setattr(cfg, field, tuple(value) if isinstance(value, list) else value)
    if getattr(args, "echo_test", False) and args.rician is None:
        cfg.rician_db = 6.0        # your own keying, with the echo under it
    if args.qrss is not None:
        apply_qrss(cfg, args.qrss, keep_rise=args.rise_ms is not None,
                   keep_rate=args.rate is not None)
    if args.no_noise:
        cfg.snr_db = None
    if args.no_limit:
        cfg.limit = False
    if cfg.seed is None:
        cfg.seed = secrets.randbelow(2**31)  # reported, so any run can be repeated
    return cfg


def slug(text: str, limit: int = 48) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (out[:limit].rstrip("-") or "morse")


def wrap(label: str, parts: list[str], indent: str = "            ",
         width: int = 86) -> list[str]:
    """One report line, continued on the next if the facts do not fit."""
    lines: list[str] = []
    current = label
    for part in parts:
        candidate = current + ("" if current.endswith(" ") or not current.strip()
                               else ", ") + part
        if len(candidate) > width and current.strip():
            lines.append(current)
            current = indent + part
        else:
            current = candidate
    if current.strip():
        lines.append(current)
    return lines


def hz(value: float, signed: bool = False) -> str:
    """A frequency, from hundreds of Hz down to milliHertz, legibly.

    This program covers both a storm core spread over 300 Hz and a 2200 m
    skywave trace two thousandths of a Hz wide; one format cannot do both.
    """
    value = float(value)
    size = abs(value)
    sign = "+" if signed else ""
    if size >= 100:
        return f"{value:{sign}.0f} Hz"
    if size >= 10:
        return f"{value:{sign}.1f} Hz"
    if size >= 1:
        return f"{value:{sign}.2f} Hz"
    if size >= 0.01:
        return f"{value:{sign}.3f} Hz"
    return f"{value * 1000:{sign}.2f} mHz"


def wavelength(mm: float) -> str:
    return f"{mm / 1000.0:.1f} m" if mm >= 1000 else f"{mm:.1f} mm"


def per_mps(value: float) -> str:
    if value >= 10:
        return f"{value:.0f} Hz per m/s"
    if value >= 0.1:
        return f"{value:.2f} Hz per m/s"
    return f"{value * 1000:.2f} mHz per m/s"


def minutes(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 180 else f"{seconds / 60:.0f} min"


def describe_qrss(qrss: dict, bandwidth: float, asked: float | None) -> list[str]:
    """What QRSS buys, and what the path takes back off it."""
    if not qrss:
        return []
    lines = wrap(f"  qrss      {qrss['label']}: ", [
        f"dit {qrss['dit_s']:g} s",
        f"read in a bin {hz(qrss['bandwidth_hz'])} wide",
        f"{qrss['processing_gain_db']:+.0f} dB on the {bandwidth:.0f} Hz filter",
    ])
    if qrss.get("waterfall_snr_db") is not None:
        asked_db = f"S/N {asked:+.0f} dB" if asked is not None else "the signal"
        lines.append(f"            so {asked_db} in the filter reads "
                     f"{qrss['waterfall_snr_db']:+.0f} dB on the waterfall")
    drift = float(qrss.get("drift_hz") or 0.0)
    if drift > qrss["bandwidth_hz"]:
        lines.append(f"            the rig's own \u00b1{hz(drift)} of drift is "
                     f"{drift / qrss['bandwidth_hz']:.0f} bins wide: lock it, or the "
                     "trace wanders off its own line")
    if qrss.get("smeared"):
        lines.append(f"            the path is wider than the bin, so the trace smears "
                     f"and {qrss['smear_db']:+.1f} dB of that goes")
    return lines


def describe_scatter(meta: dict, scatter: dict) -> list[str]:
    """The propagation half of the report: the path, the cloud, the verdict."""
    lines = [f"  path      {meta['band']}, \u03bb {wavelength(meta['wavelength_mm'])}, "
             f"{per_mps(meta['hz_per_mps'])}"]
    geometry = scatter.get("geometry")
    if geometry:
        volume = "\u00d7".join(f"{v:g}" for v in geometry["volume_km"])
        lines.extend(wrap("            geometry  ", [
            f"{geometry['elevation_deg']:.1f}\u00b0 this end and "
            f"{geometry['far_elevation_deg']:.1f}\u00b0 the other",
            f"{geometry['squint_deg']:.0f}\u00b0 off the path",
            f"volume {geometry['height_km']:.1f} km up, {volume} km",
            f"bistatic {geometry['bistatic_deg']:.0f}\u00b0",
            f"so {geometry['sensitivity']:.2f} of any motion is heard",
            f"stations {geometry['baseline_km']:.0f} km apart",
        ]))

    head = f"{scatter.get('cell', '')} {scatter['kind']}".strip()
    if "rate_mm_h" in scatter:
        head += f" {scatter['rate_mm_h']:.3g} mm/h, {scatter['dbz']:.0f} dBZ"
    if scatter["kind"] == "moon":
        head += f" at {scatter['distance_km']:,.0f} km"
    if scatter["kind"] == "skywave":
        head += f", {len(scatter.get('modes', []))} mode(s)"
    tuned = scatter.get("tuned_out_hz") or 0.0
    tracked = "tracked out" if scatter.get("tracking") else "tuned out"
    doppler = (f"Doppler {hz(tuned, signed=True)} {tracked}" if tuned
               else f"Doppler {hz(scatter['shift_hz'], signed=True)}")
    lines.append(f"  scatter   {head}: {doppler}, spread "
                 f"{hz(scatter['spread_hz'])}, "
                 f"{scatter['audible_fraction'] * 100:.0f}% inside the filter")
    if scatter.get("sounds_like"):
        lines.append(f"            \u2014 {scatter['sounds_like']}")

    cores = scatter.get("cores") or []
    if len(cores) > 1:
        detail = [f"{c['shift_hz']:+.0f} Hz/{c['spread_hz']:.0f} Hz "
                  f"at {c['level_db']:+.0f} dB" for c in cores]
        lines.extend(wrap(f"            {len(cores)} cores  ", detail))

    if scatter["kind"] == "aircraft":
        lines.extend(wrap("            ", [
            f"{scatter['speed_mps']:.0f} m/s at {scatter['altitude_km']:.1f} km, "
            f"heading {scatter['heading_deg']:.0f}° across a "
            f"{scatter['baseline_km']:.0f} km path",
            f"sliding {hz(scatter['sweep_hz_s'], signed=True)} a second, "
            f"{hz(scatter['doppler_from_hz'], signed=True)} to "
            f"{hz(scatter['doppler_to_hz'], signed=True)}",
            f"{scatter['length_m']:.0f} m of aeroplane, so "
            f"{hz(scatter['spread_hz'])} of roughness on the note",
            f"loudest {scatter['best_at_s']:.0f} s in, usable for "
            f"{scatter['window_s']:.0f} s",
        ]))
        return lines + _budget(scatter)

    if scatter["kind"] == "moon":
        lines.extend(wrap("            ", [
            f"the echo is {scatter['delay_s']:.2f} s late",
            f"libration {scatter['libration_deg_day']:.2f}\u00b0 a day, "
            f"limb {hz(scatter['limb_hz'])}",
            f"{scatter['scatterers']} patches, cos^{scatter['scatter_law']:.1f} "
            "across the disc",
        ]))
        drift = [f"own Doppler {hz(scatter['own_doppler_hz'], signed=True)}",
                 f"drifting {hz(scatter['drift_hz_s'], signed=True)} a second"]
        drift.append("both followed" if scatter.get("tracking")
                     else "the drift left in, so the trace slopes")
        if (scatter.get("faraday_db") or 0) > 0.5:
            drift.append(f"Faraday {scatter['faraday_db']:.0f} dB nulls every "
                         f"{minutes(scatter['faraday_period_s'])}")
        lines.extend(wrap("            ", drift))
        return lines + _budget(scatter)

    if scatter["kind"] == "skywave":
        rise = scatter["height_rate_mps"]
        detail = [
            f"layer {'rising' if rise >= 0 else 'falling'} {abs(rise):.2f} m/s at "
            f"{scatter['elevation_deg']:.0f}\u00b0 take-off",
            f"wandering {hz(scatter['wander_hz'])}",
        ]
        if len(scatter.get("modes", [])) > 1:
            detail.append(f"modes {hz(scatter['between_hz'])} apart, so it fades every "
                          f"{minutes(scatter['fade_period_s'])}")
        lines.extend(wrap("            ", detail))
        return lines + _budget(scatter)

    sampled = [f"{scatter['scatterers']} scatterers"]
    if "median_drop_mm" in scatter:
        sampled.append(f"median drop {scatter['median_drop_mm']:.1f} mm")
    if "median_melted_mm" in scatter:
        sampled.append(f"median flake {scatter['median_melted_mm']:.1f} mm melted")
    if "updraft_mps" in scatter:
        sampled.append(f"lift {scatter['updraft_mps']:+.1f} m/s "
                       f"\u00b1{scatter.get('lift_gradient_mps_km', 0.0):.1f} per km")
        sampled.append(f"turbulence {scatter['turbulence_mps']:.1f} m/s")
    if "wind_mps" in scatter:
        sampled.append(f"wind {scatter['wind_mps']:.0f} m/s from "
                       f"{scatter['wind_azimuth_deg']:.0f}\u00b0 "
                       f"({scatter['wind_along_mps']:+.1f} m/s along the bisector)")
        sampled.append(f"shear {scatter['shear_mps_km']:.0f} m/s per km")
    if scatter.get("evolving"):
        sampled.append(f"rearranging every {1.0 / max(scatter['evolve_rate_hz'], 1e-3):.1f} s")
    elif "evolve_rate_hz" in scatter:
        sampled.append("held still")
    if scatter.get("scintillation_db"):
        sampled.append(f"QSB {scatter['scintillation_db']:.0f} dB on top")
    if scatter.get("from_physics") is False:
        sampled.append("Doppler set by hand")
    lines.extend(wrap("            ", sampled))

    return lines + _budget(scatter)


def _budget(scatter: dict) -> list[str]:
    """What the path did to the signal level, in dB, and the honest warnings."""
    lines: list[str] = []
    budget = []
    if scatter.get("level_offset_db"):
        budget.append(f"reflectivity {scatter['level_offset_db']:+.1f} dB")
    if scatter.get("filter_loss_db", 0.0) < -0.5:
        budget.append(f"outside the filter {scatter['filter_loss_db']:+.1f} dB")
    if budget:
        lines.append("            on the signal: " + ", ".join(budget))
    if scatter.get("attenuation_db"):
        lines.append("            on the way: path attenuation "
                     f"-{scatter['attenuation_db']:.1f} dB")
    if scatter["audible_fraction"] < 0.05:
        lines.append("            nothing survives the filter at this band "
                     "\u2014 try --band 144M, or --doppler-spread")
    return lines


def describe(result: Render, heading: str, profile: str) -> str:
    m = result.meta
    lines = [heading]
    code = str(m["code"])
    lines.append(f"  text      {m['text']}")
    lines.append(f"  code      {code if len(code) <= 96 else code[:93] + '...'}")
    spacing = (f"Farnsworth to {m['effective_wpm']:.0f} wpm"
               if m["farnsworth"] else "standard spacing")
    speed = f"{m['wpm']:.2f} wpm" if m["wpm"] < 5 else f"{m['wpm']:.0f} wpm"
    dit = (f"dit {m['dit_ms'] / 1000.0:g} s" if m["dit_ms"] >= 1000
           else f"dit {m['dit_ms']:.1f} ms")
    lines.append(f"  keying    {speed}, {dit}, {spacing}")
    cfg = m["config"]
    tone = f"  tone      {m['tone_hz']:.0f} Hz"
    extras = []
    if cfg["drift_hz"]:
        extras.append(f"drift ±{hz(cfg['drift_hz'])}")
    if cfg["qsb_db"]:
        extras.append(f"QSB {cfg['qsb_db']:.0f} dB")
    if cfg["hum_depth"]:
        extras.append(f"hum {cfg['hum_depth'] * 100:.0f}% at {cfg['hum_hz']:.0f} Hz")
    lines.append(tone + (", " + ", ".join(extras) if extras else ""))

    scatter = m.get("scatter") or {}
    if scatter:
        lines.extend(describe_scatter(m, scatter))

    if m["snr_db"] is None:
        lines.append(f"  band      {profile}: no noise")
    else:
        effective = m.get("effective_snr_db", m["snr_db"])
        band = [f"S/N {effective:.0f} dB in {cfg['bandwidth']:.0f} Hz"]
        if abs(float(effective) - float(m["snr_db"])) > 0.05:
            band[0] += f" (asked {m['snr_db']:.0f}, weather {effective - m['snr_db']:+.0f})"
        if cfg["crash_rate"]:
            band.append(f"QRN {cfg['crash_rate']:.2g}/s at +{cfg['crash_db']:.0f} dB")
        if m["measured_snr_db"] is not None:
            band.append(f"measured {m['measured_snr_db']:.1f} dB")
        lines.append(f"  band      {profile}: " + ", ".join(band))
        noise = m["noise"] or {}
        for note in list(noise.get("qrm", [])) + list(noise.get("birdies", [])):
            lines.append(f"            {note}")
    lines.extend(describe_qrss(m.get("qrss") or {}, float(cfg["bandwidth"]),
                               m.get("effective_snr_db")))
    if m["unknown"]:
        lines.append(f"  skipped   {' '.join(m['unknown'])} (no Morse equivalent)")
    size = (result.samples.size * 2 + 44) / 1024
    lines.append(f"  audio     {result.duration:.1f} s, {m['sample_rate']} Hz, "
                 f"{size:.0f} KB, seed {m['seed']}")
    return "\n".join(lines)


def messages(args: argparse.Namespace) -> list[str]:
    if args.batch:
        text = Path(args.batch).read_text(encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines()]
        return [ln for ln in lines if ln and not ln.startswith("#")]
    joined = " ".join(args.text).strip()
    return [joined or DEFAULT_TEXT]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_profiles:
        width = max(len(n) for n in PROFILES)
        for group, detail in GROUPS.items():
            print(f"{group}  \u2014 {detail['about']}")
            for name in detail["profiles"]:
                mark = " (default)" if name == DEFAULT_PROFILE else ""
                print(f"  {name:<{width}}  {DESCRIPTIONS.get(name, '')}{mark}")
            print()
        return 0
    if args.list_players:
        print(describe_players())
        return 0

    try:
        texts = messages(args)
    except OSError as err:
        parser.error(str(err))
    if not texts:
        parser.error("no messages to key")

    writing = bool(args.out or args.batch)
    playing = args.play or not writing
    player = None
    if playing:
        try:
            player = find_player(args.player)
        except PlaybackError as err:
            print(f"morsefun: {err}", file=sys.stderr)
            return 2

    cfg = config_from_args(args)
    outdir = Path(args.outdir)
    rendered: list[tuple[Render, Path | None]] = []

    for index, text in enumerate(texts):
        seed = cfg.seed if len(texts) == 1 else cfg.seed + index
        result = render(text, replace(cfg, seed=seed))
        if not result.meta["characters"]:
            print(f"nothing to key in {text!r}", file=sys.stderr)
            continue

        path = None
        if writing:
            if args.batch:
                path = outdir / f"{index + 1:03d}-{slug(text)}.wav"
            elif args.out:
                path = Path(args.out)
            else:
                path = outdir / f"{slug(text)}.wav"
            write_wav(path, result.samples, result.sample_rate)
        rendered.append((result, path))

        if not args.json and not args.quiet:
            heading = str(path) if path else f"playing through {player.name}"
            if path and playing:
                heading += f"  (and playing through {player.name})"
            if playing and args.repeat > 1:
                heading += f", {args.repeat}\u00d7 {args.gap:.1f} s apart"
            print(describe(result, heading, args.profile), flush=True)

        if playing:
            try:
                play(result.samples, result.sample_rate, args.player, args.repeat, args.gap)
            except PlaybackError as err:
                print(f"morsefun: {err}", file=sys.stderr)
                return 2
            except KeyboardInterrupt:
                print("\nstopped.", file=sys.stderr)
                return 130

    if not rendered:
        return 1
    if args.json:
        print(json.dumps(
            [{"file": str(p) if p else None,
              **{k: v for k, v in r.meta.items() if k != "config"}}
             for r, p in rendered],
            indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
