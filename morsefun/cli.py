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
from .profiles import DEFAULT_PROFILE, DESCRIPTIONS, PROFILES
from .render import Config, Render, render
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
    w.add_argument("--scatter", choices=("none", "rain", "snow", "aurora"),
                   help="what the signal bounces off (default: none)")
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


def describe_scatter(meta: dict, scatter: dict) -> list[str]:
    """The propagation half of the report: the path, the cloud, the verdict."""
    lines = [f"  path      {meta['band']}, \u03bb {meta['wavelength_mm']:.1f} mm, "
             f"{meta['hz_per_mps']:.0f} Hz per m/s"]
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
    tuned = scatter.get("tuned_out_hz") or 0.0
    doppler = (f"Doppler {tuned:+.0f} Hz tuned out" if tuned
               else f"Doppler {scatter['shift_hz']:+.0f} Hz")
    lines.append(f"  scatter   {head}: {doppler}, spread "
                 f"{scatter['spread_hz']:.0f} Hz, "
                 f"{scatter['audible_fraction'] * 100:.0f}% inside the filter")
    if scatter.get("sounds_like"):
        lines.append(f"            \u2014 {scatter['sounds_like']}")

    cores = scatter.get("cores") or []
    if len(cores) > 1:
        detail = [f"{c['shift_hz']:+.0f} Hz/{c['spread_hz']:.0f} Hz "
                  f"at {c['level_db']:+.0f} dB" for c in cores]
        lines.extend(wrap(f"            {len(cores)} cores  ", detail))

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
    lines.append(f"  keying    {m['wpm']:.0f} wpm, dit {m['dit_ms']:.1f} ms, {spacing}")
    cfg = m["config"]
    tone = f"  tone      {m['tone_hz']:.0f} Hz"
    extras = []
    if cfg["drift_hz"]:
        extras.append(f"drift ±{cfg['drift_hz']:.1f} Hz")
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
        for name in sorted(PROFILES):
            mark = " (default)" if name == DEFAULT_PROFILE else ""
            print(f"{name:<{width}}  {DESCRIPTIONS.get(name, '')}{mark}")
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
